"""Small explicit judgments only; no fabricated empirical ground truth."""
from __future__ import annotations

import math

from research.models import ResearchProject
from research.relevance import ResearchProfile


def evaluate(fixture: dict, k: int = 3) -> dict:
    if k <= 0:
        raise ValueError('K must be positive.')
    profile=ResearchProfile(ResearchProject(**fixture['project']))
    documents=fixture['documents']
    ordered=sorted(documents,key=lambda row:(-profile.score(row['title'],row['text']).score,row['id']))
    selected=ordered[:k]
    positives=sum(row['relevant'] for row in documents)
    hits=sum(row['relevant'] for row in selected)
    dcg=sum(row['relevant']/math.log2(index+2) for index,row in enumerate(selected))
    ideal=sum(1/math.log2(index+2) for index in range(min(positives,k)))
    return {'k':k,'precision_at_k':hits/k,'recall_at_k':hits/positives if positives else 0,
            'ndcg_at_k':dcg/ideal if ideal else 0,'ranking':[row['id'] for row in ordered],
            'provenance':fixture['provenance'],'label_rule':fixture['label_rule']}


def compare_tfidf(fixture: dict, k: int = 3) -> dict:
    """Explicit benchmark-only comparison; never fit a growing crawl corpus."""
    if k<=0:raise ValueError('K must be positive.')
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    from core.text import tokenize
    project=fixture['project'];documents=fixture['documents']
    query=' '.join((project['title'],project.get('description',''),*project.get('keywords',[])))
    texts=[query]+[row['title']+' '+row['text'] for row in documents]
    matrix=TfidfVectorizer(tokenizer=tokenize,token_pattern=None,lowercase=False,max_features=5000).fit_transform(texts)
    similarities=cosine_similarity(matrix[:1],matrix[1:]).ravel()
    ordered=sorted(zip(documents,similarities),key=lambda pair:(-float(pair[1]),pair[0]['id']))
    positives=sum(row['relevant'] for row in documents)
    hits=sum(row['relevant'] for row,_ in ordered[:k])
    dcg=sum(row['relevant']/math.log2(index+2) for index,(row,_) in enumerate(ordered[:k]))
    ideal=sum(1/math.log2(index+2) for index in range(min(positives,k)))
    return {'method':'TF-IDF unigram cosine, fitted to query plus authored fixture only',
        'precision_at_k':hits/k,'recall_at_k':hits/positives if positives else 0,
        'ndcg_at_k':dcg/ideal if ideal else 0,'ranking':[row['id'] for row,_ in ordered],
        'scores':{row['id']:float(score) for row,score in ordered},
        'notice':'Corpus-dependent benchmark comparator, not a calibrated probability or real-world accuracy estimate.'}
