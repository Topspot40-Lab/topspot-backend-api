"""Narration choices for Artist Spotlight programs, separate from Radio sets."""


def spotlight_narration_choices(selection: dict, context: dict) -> tuple[str, str]:
    # Keep old clients' long-detail behavior; new clients send their choice.
    detail = selection.get('detailLength') or selection.get('detail_length') or 'long'
    bio = context.get('bio_length') or 'short'
    if detail not in {'off', 'short', 'long'}:
        raise ValueError('detail_length must be one of: off, short, long')
    if bio not in {'short', 'long'}:
        raise ValueError('bio_length must be one of: short, long')
    return detail, bio


def spotlight_bio_asset(metadata: dict, bio_length: str) -> tuple[str | None, str | None]:
    """Only use the requested biography length in the requested language."""
    return metadata.get(f'{bio_length}_bucket'), metadata.get(f'{bio_length}_key')
