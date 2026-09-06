from jobbot.dedupe import deduplicate


def job(source, title, company, url, detail="", status="OK_HTML", location="Spain"):
    return {
        "source": source,
        "title": title,
        "company": company,
        "url": url,
        "location": location,
        "full_detail": detail,
        "detail_status": status,
    }


def test_same_title_company_across_sources_merges():
    rows = [
        job("Biocat", "Research Project Manager", "Example Institute", "https://a/jobs/1", "research project management health consortium participant data collection" * 20),
        job("EURAXESS", "Research Project Manager", "Example Institute", "https://b/jobs/99", "research project management health consortium participant data collection" * 20),
    ]
    out, removed = deduplicate(rows)
    assert removed == 1 and len(out) == 1
    assert set(out[0]["also_seen_in"]) == {"Biocat", "EURAXESS"}
    assert len(out[0]["alternate_urls"]) == 2


def test_generic_same_title_different_jobs_do_not_merge():
    rows = [
        job("Biocat", "Postdoctoral Fellow", "Institute Alpha", "https://a/1", "cell signaling kinase microscopy phosphoproteomics " * 30),
        job("EURAXESS", "Postdoctoral Fellow", "Institute Beta", "https://b/2", "exercise intervention physical activity cognition stress participants " * 30),
    ]
    out, removed = deduplicate(rows)
    assert removed == 0 and len(out) == 2


def test_alias_employers_merge_when_validated_jd_is_same():
    # Mirrors the general pattern IRB-style long legal name vs short institutional name;
    # no literal company alias is hard-coded in production code.
    core = ("postdoctoral fellow crosstalk analysis mapk signaling cell signaling kinase "
            "single cells microscopy phosphorylation mass spectrometry mammalian cells ") * 25
    rows = [
        job("Biocat", "Postdoctoral Fellow", "Institute for Biomedical Research of Barcelona", "https://employer/jobs/pd", core + " employer benefits " * 10),
        job("EURAXESS", "Postdoctoral Fellow", "IBR Barcelona", "https://euraxess/jobs/1", "job information country spain " + core),
    ]
    out, removed = deduplicate(rows)
    assert removed == 1 and len(out) == 1


def test_unresolved_record_is_enriched_by_resolved_duplicate():
    unresolved = job("Biocat", "Health Research Coordinator", "Institute X", "https://a/job", "", "DETAIL_MISMATCH")
    resolved = job("EURAXESS", "Health Research Coordinator", "Institute X", "https://b/job", "participant recruitment study coordination data management consortium reporting " * 20, "OK_HTML")
    out, removed = deduplicate([unresolved, resolved])
    assert removed == 1
    assert out[0]["detail_status"] == "OK_HTML"
    assert out[0]["full_detail"]


def test_same_url_merges_even_if_source_labels_differ():
    rows = [
        job("Biocat", "Role A", "Org", "https://example.org/job/1?utm_source=x", "detail one"),
        job("Other", "Role A", "Org", "https://example.org/job/1", "detail one"),
    ]
    out, removed = deduplicate(rows)
    assert removed == 1 and len(out) == 1


def test_fuzzy_title_requires_strong_company_or_detail_evidence():
    rows = [
        job("Biocat", "Research Assistant - Mental Health Project", "Org Alpha", "https://a/1", "mental health project participant data " * 20),
        job("EURAXESS", "Research Assistant Mental Health Project at Barcelona", "Org Beta", "https://b/2", "different laboratory molecular assay " * 20),
    ]
    out, removed = deduplicate(rows)
    assert removed == 0 and len(out) == 2


def test_distinct_reference_ids_prevent_merge_despite_shared_project_text():
    shared = "horizon europe doctoral network project engineering international consortium training " * 35
    rows = [
        job("EURAXESS", "HRER2026/329-159 INVESTIGADOR / Researcher", "University X", "https://e/jobs/1", shared + "wireless charging drones rovers"),
        job("EURAXESS", "HRER2026/328-158 INVESTIGADOR / Researcher", "University X", "https://e/jobs/2", shared + "power converter control systems"),
    ]
    out, removed = deduplicate(rows)
    assert removed == 0 and len(out) == 2
