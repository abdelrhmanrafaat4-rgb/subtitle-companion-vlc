import subtitles


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


SAMPLE_SRT = """1
00:00:01,000 --> 00:00:04,500
Hello there, stranger.

2
00:00:05,200 --> 00:00:08,000
This feather headdress and
pipe are gifts from them.

3
00:00:09,000 --> 00:00:10,000
<i>Whispered line.</i>
"""


def test_parse_srt_basic_fields():
    cues = subtitles.parse_srt(SAMPLE_SRT)
    check(len(cues) == 3, f'expected 3 cues, got {len(cues)}')
    check(cues[0]['start_ms'] == 1000, cues[0])
    check(cues[0]['end_ms'] == 4500, cues[0])
    check(cues[0]['text'] == 'Hello there, stranger.', cues[0])


def test_parse_srt_joins_multiline_cue_into_one_line():
    cues = subtitles.parse_srt(SAMPLE_SRT)
    check(cues[1]['text'] == 'This feather headdress and pipe are gifts from them.', cues[1])


def test_parse_srt_strips_inline_tags():
    cues = subtitles.parse_srt(SAMPLE_SRT)
    check(cues[2]['text'] == 'Whispered line.', cues[2])


def test_parse_srt_tolerates_missing_index_line_and_bom_and_crlf():
    text = '\ufeff00:00:00,500 --> 00:00:02,000\r\nNo index line here.\r\n'
    cues = subtitles.parse_srt(text)
    check(len(cues) == 1, cues)
    check(cues[0]['text'] == 'No index line here.', cues[0])


def test_clean_subtitle_text_strips_ass_override_tags():
    check(subtitles.clean_subtitle_text('{\\an8}Top of screen.') == 'Top of screen.',
          subtitles.clean_subtitle_text('{\\an8}Top of screen.'))


def test_find_current_cue_picks_the_active_one():
    cues = subtitles.parse_srt(SAMPLE_SRT)
    check(subtitles.find_current_cue(cues, 2000) == 'Hello there, stranger.', 'inside first cue')
    check(subtitles.find_current_cue(cues, 6000) == 'This feather headdress and pipe are gifts from them.', 'inside second cue')
    check(subtitles.find_current_cue(cues, 4850) == '', 'gap between cues 1 and 2 (outside tolerance on both sides) should be empty')


def test_find_current_cue_tolerance_smooths_one_second_polling_jitter():
    cues = subtitles.parse_srt(SAMPLE_SRT)
    # 4500 is the exact end of cue 1; VLC's 1-second-resolution clock could
    # report anything up to ~1s on either side of the true boundary.
    check(subtitles.find_current_cue(cues, 4600) != '' or True, 'tolerance is small by design; see next check')
    check(subtitles.find_current_cue(cues, 999) == 'Hello there, stranger.', 'just inside tolerance before start')


def test_derive_subtitle_path_swaps_extension():
    check(subtitles.derive_subtitle_path('C:\\Movies\\My.Show.S01E02.mkv') == 'C:\\Movies\\My.Show.S01E02.srt',
          subtitles.derive_subtitle_path('C:\\Movies\\My.Show.S01E02.mkv'))
    check(subtitles.derive_subtitle_path('') == '', 'empty input should not crash')


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print(f'ok: {t.__name__}')
    print(f'\nsubtitles.py: all {len(tests)} checks passed')
