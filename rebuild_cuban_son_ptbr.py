"""Rebuild Cuban Son PT-BR with reviewed narration and a quieter bed. No uploads."""
import argparse
import json
import os
import subprocess
from pathlib import Path


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_format', '-show_streams',
        '-of', 'json', str(path)], text=True))


def duration(path):
    return float(probe(path)['format']['duration'])


def rebuild(root, bed):
    source = root / 'factory/delivery/pt-BR/documentary.mp4'
    original = root / 'factory/delivery/pt-BR/narration'
    corrected = root / 'corrected-narration/pt-BR/story.mp3'
    frame = root / 'previews/hook_title_pt-BR.png'
    output = root / 'updated-delivery/pt-BR/documentary_corrected_voice.mp4'
    parts = [original / 'hook.mp3', original / 'intro.mp3', corrected, original / 'outro.mp3']
    for path in [source, original / 'story.mp3', frame, bed, *parts]:
        if not path.is_file():
            raise FileNotFoundError(path)
    if output.exists():
        raise FileExistsError(f'Output already exists; choose a new name or move it aside: {output}')
    lengths = [duration(path) for path in parts]
    old_story = duration(original / 'story.mp3')
    source_data = probe(source)
    old_total = float(source_data['format']['duration'])
    video_stream = next(s for s in source_data['streams'] if s['codec_type'] == 'video')
    if abs(float(video_stream.get('duration', old_total)) - old_total) > .25:
        raise RuntimeError('Source video and audio durations differ; inspect source before rebuilding')
    story_start = 6.5 + lengths[0] + 1.25 + lengths[1] + .75
    old_end = story_start + old_story
    expected = old_end + 3 + lengths[3] + 2
    if abs(expected - old_total) > .25:
        raise RuntimeError(f'Source timing mismatch: expected {expected:.3f}s, actual {old_total:.3f}s')
    new_total = old_total - old_story + lengths[2]
    ratio = lengths[2] / old_story
    hook_end = 6.5 + lengths[0] + 1.25
    filters = [
        '[0:v]split=3[pre][story][post]',
        f'[pre]trim=start=0:end={story_start},setpts=PTS-STARTPTS[p]',
        f'[story]trim=start={story_start}:end={old_end},setpts=(PTS-STARTPTS)*{ratio:.12f}[s]',
        f'[post]trim=start={old_end},setpts=PTS-STARTPTS[e]',
        '[p][s][e]concat=n=3:v=1:a=0,fps=30[retimed]',
        f"[retimed][6:v]overlay=0:0:shortest=1:enable='gte(t,6.5)*lt(t,{hook_end})'[v]",
    ]
    starts = [6.5, 6.5 + lengths[0] + 1.25, story_start, story_start + lengths[2] + 3]
    for index, (start, length) in enumerate(zip(starts, lengths), 1):
        delay = round(start * 44100)
        filters.append(f'[{index}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                       f'apad,atrim=duration={length},asetpts=PTS-STARTPTS,adelay={delay}S:all=1[n{index}]')
    filters.extend([
        f'[n1][n2][n3][n4]amix=inputs=4:normalize=0:duration=longest,apad,atrim=duration={new_total},asplit=2[voice][duck]',
        f'[5:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=duration={new_total},'
        f'asetpts=PTS-STARTPTS,volume=-29dB,afade=t=in:st=0:d=4,afade=t=out:st={new_total-4}:d=4[music]',
        '[music][duck]sidechaincompress=threshold=0.03:ratio=8:attack=25:release=500[softmusic]',
        '[voice][softmusic]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95:level=false:latency=true[a]',
    ])
    command = ['ffmpeg', '-hide_banner', '-n', '-i', str(source)]
    for path in parts:
        command += ['-i', str(path)]
    command += ['-stream_loop', '-1', '-i', str(bed), '-loop', '1', '-framerate', '30', '-i', str(frame),
                '-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-t', str(new_total), '-movflags', '+faststart', str(output)]
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f'Retiming story: {old_story:.3f}s -> {lengths[2]:.3f}s; bed -29 dB', flush=True)
    subprocess.run(command, check=True)
    result = probe(output)
    for kind in ('video', 'audio'):
        stream = next(s for s in result['streams'] if s['codec_type'] == kind)
        if abs(float(stream['duration']) - new_total) > .25:
            raise RuntimeError(f'{kind} duration verification failed; do not upload this output')
    print(f'Verified video/audio duration: {new_total:.3f}s\nSaved: {output.resolve()}')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('backend/studio/work/story_of_cuban_son'))
    parser.add_argument('--bed', type=Path, default=Path('backend/studio/work/george_martin/factory/cache/audio/bed_01.mp3'))
    args = parser.parse_args()
    output = rebuild(args.root, args.bed)
    if hasattr(os, 'startfile'):
        os.startfile(output.resolve())
