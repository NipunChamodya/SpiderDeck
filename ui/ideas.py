"""Research idea management and offline comparison in the existing terminal UI."""
from __future__ import annotations

import json
from contextlib import closing
from dataclasses import replace

from core.config import RankingConfig
from core.storage import RecordStore, StorageError
from rank.models import SCORE_NOTICE, ResearchIdea
from rank.supervisor_ranker import rank_records
from security.filesystem import new_output_text
from ui import menu
from ui.records import prompt_filters, terminal_text

ACTIONS = ["List ideas", "Create idea", "Edit idea", "Remove idea", "Compare ideas", "Back"]


def _choose(ideas: list[ResearchIdea], *, multiple: bool = False) -> list[ResearchIdea]:
    labels = {f"{index}) {terminal_text(idea.title)} [{idea.idea_id[:8]}]": idea
              for index, idea in enumerate(ideas, 1)}
    choices = list(labels)
    if multiple:
        selected = menu.prompt_multiple("Select research ideas (Space toggles, Enter confirms):", choices)
        return [labels[label] for label in selected if label in labels]
    selected = menu.prompt_choice("Research idea:", choices)
    return [labels[selected]] if selected in labels else []


def _edit(original: ResearchIdea | None = None) -> ResearchIdea:
    def text(label: str, previous: str = "") -> str:
        hint = " (blank keeps current, - clears)" if original is not None else ""
        entered = menu.prompt_text(label + hint + ":")
        if original is not None and not entered:
            return previous
        return "" if entered == "-" else entered

    title = text("Title", original.title if original else "")
    description = text("Description", original.description if original else "")
    keywords = text("Comma-separated keywords", ", ".join(original.keywords) if original else "")
    domain = text("Domain/category (optional)", original.domain or "" if original else "")
    raw_weights = text("Keyword weights as JSON, e.g. {\"vision\": 2} (optional)",
                       json.dumps(original.keyword_weights, ensure_ascii=False) if original else "")
    try:
        weights = json.loads(raw_weights) if raw_weights.strip() else {}
    except (ValueError, RecursionError) as exc:
        raise ValueError("Keyword weights must be a valid JSON object.") from exc
    data = dict(title=title, description=description,
                keywords=tuple(term.strip() for term in keywords.split(",") if term.strip()),
                domain=domain or None, keyword_weights=weights)
    return replace(original, **data) if original else ResearchIdea(**data)


def _compare(store: RecordStore, ideas: list[ResearchIdea], config: RankingConfig) -> None:
    selected = _choose(ideas, multiple=True)
    if not selected:
        return
    filters = prompt_filters()
    with closing(store.iter_records(filters)) as records:
        results = rank_records(records, selected, config)
    print(SCORE_NOTICE)
    print("Scores run from 0 to 1 and depend on the selected corpus and configured weights.")
    print(f"Weights: text={config.text_weight}, keyword={config.keyword_weight}, domain={config.domain_weight}. "
          "Keyword/domain scoring applies only when its weight is positive.")
    for result in results:
        print(f"\nIdea: {terminal_text(result.idea_title)} | {result.candidate_count} candidates")
        for warning in result.warnings:
            print(f"Notice: {terminal_text(warning, 300)}")
        for index, match in enumerate(result.matches, 1):
            print(f"{index}. {terminal_text(match.supervisor_name or 'Unnamed document record')} | {match.score:.3f}")
            print(f"  Matched terms: {terminal_text(', '.join(match.matched_terms), 400) or '(none)'}")
            for source in match.sources:
                print(f"  Source: {terminal_text(source, 300)}")
            print(f"  Reason: {terminal_text(match.reason, 500)}")
            for uncertainty in match.uncertainties:
                print(f"  Uncertainty: {terminal_text(uncertainty, 300)}")
    if menu.confirm("Save this comparison as JSON?"):
        filename = menu.prompt_text("New .json filename under output:")
        if not filename:
            return
        if not filename.lower().endswith(".json"):
            raise ValueError("Comparison export filename must end with .json.")
        with new_output_text(store.root, filename) as handle:
            json.dump({"method": "TF-IDF cosine and optional weighted lexical matching",
                       "weights": {"text": config.text_weight, "keyword": config.keyword_weight,
                                   "domain": config.domain_weight},
                       "filters": {"keyword": filters.keyword, "source": filters.source,
                                   "source_type": filters.source_type},
                       "ideas": [idea.to_dict() for idea in selected],
                       "score_notice": SCORE_NOTICE, "rankings": [result.to_dict() for result in results]},
                      handle, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
            handle.write("\n")
        print("Comparison exported.")


def run(store: RecordStore, config: RankingConfig) -> None:
    while True:
        action = menu.prompt_choice("Research ideas and ranking:", ACTIONS)
        if action in {None, "Back"}:
            return
        try:
            ideas = store.list_ideas()
            if action == "Create idea":
                store.add_idea(_edit())
                print("Research idea saved locally.")
            elif action == "List ideas":
                if not ideas:
                    print("No saved research ideas. Choose Create idea to begin.")
                for idea in ideas:
                    print(f"{idea.idea_id[:8]} | {terminal_text(idea.title)}")
                    print(f"  {terminal_text(idea.description, 400) or '(no description)'}")
                    print(f"  Keywords: {terminal_text(', '.join(idea.keywords), 400) or '(none)'}")
                    print(f"  Domain: {terminal_text(idea.domain or '(none)')}")
                    print(f"  Keyword weights: {terminal_text(json.dumps(idea.keyword_weights, ensure_ascii=False), 400)}")
            elif not ideas:
                print("No saved research ideas. Choose Create idea to begin.")
            elif action == "Compare ideas":
                _compare(store, ideas, config)
            elif action in {"Edit idea", "Remove idea"}:
                selected = _choose(ideas)
                if not selected:
                    continue
                if action == "Edit idea":
                    print("Current idea: " + terminal_text(selected[0].title))
                    store.update_idea(_edit(selected[0]))
                    print("Research idea updated.")
                elif menu.confirm("Remove this idea from the active list? Its stored data will be archived."):
                    store.archive_idea(selected[0].idea_id)
                    print("Research idea removed from the active list.")
        except FileExistsError:
            print("Export already exists. Choose a new filename; existing data was preserved.")
        except (StorageError, ValueError) as exc:
            print("Idea operation failed: " + terminal_text(str(exc), 300))
        except OSError:
            print("Idea operation failed. Check output permissions and disk space; existing data was preserved.")
