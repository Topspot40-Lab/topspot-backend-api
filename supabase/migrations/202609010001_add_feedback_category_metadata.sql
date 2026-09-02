begin;

alter table public.feedback
    add column if not exists category text;

alter table public.feedback
    add column if not exists metadata jsonb;

-- Preserve categories written by a prior partial deployment while classifying
-- known legacy contact forms before assigning the default to other rows.
update public.feedback
set category = 'contact'
where category is null
  and (
      title ilike '%Contact Us%'
      or title ilike '%Landing page contact message%'
  );

update public.feedback
set category = 'general_feedback'
where category is null;

update public.feedback
set metadata = '{}'::jsonb
where metadata is null;

alter table public.feedback
    alter column category set default 'general_feedback',
    alter column category set not null,
    alter column metadata set default '{}'::jsonb,
    alter column metadata set not null;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conrelid = 'public.feedback'::regclass
          and conname = 'feedback_category_check'
    ) then
        alter table public.feedback
            add constraint feedback_category_check
            check (category in ('contact', 'general_feedback', 'content_issue'));
    end if;
end $$;

create index if not exists idx_feedback_category_status_created_at
    on public.feedback (category, status, created_at desc);

commit;
