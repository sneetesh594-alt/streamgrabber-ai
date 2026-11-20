from stream_downloader.highlight_ranker import Observation, rank_highlights

def test_rejects_menus_and_no_evidence():
    assert rank_highlights([Observation(0, 30, 1, 1, 1, 1, evidence_source="")]) == []
    assert rank_highlights([Observation(0, 30, 1, 1, 1, 1, menu_probability=0.9, evidence_source="frames")]) == []

def test_picks_action_and_deduplicates():
    observations = [
        Observation(10, 40, 0.95, 0.9, 0.9, 0.8, evidence_source="sampled video and audio"),
        Observation(12, 42, 0.95, 0.8, 0.8, 0.8, evidence_source="sampled video and audio"),
        Observation(90, 120, 0.9, 0.8, 0.9, 0.8, evidence_source="sampled video and audio"),
    ]
    assert len(rank_highlights(observations)) == 2

def test_no_random_fallback():
    assert rank_highlights([]) == []
