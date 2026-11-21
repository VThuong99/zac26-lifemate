"""Offline teacher-forced data and small action-name diagnostic; no ToolEnv access."""
import copy
import json
import math
import random
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher

FINISH = "<finish>"


def build_examples(sample):
    """Yield the same history shape Agent passes, with strictly preceding results."""
    label = sample["label"]
    calls, results = label["tool_calls"], label["tool_results"]
    if len(calls) != len(results):
        raise ValueError("call/result length mismatch")
    history = copy.deepcopy(sample.get("history", []))
    for index in range(len(calls) + 1):
        target = ({"type": "finish"} if index == len(calls) else
                  {"type": "call", "name": calls[index]["name"],
                   "arguments": copy.deepcopy(calls[index]["arguments"])})
        yield {"id": sample["id"], "prefix": index, "text": sample["audio_text"],
               "context": copy.deepcopy(sample["context"]),
               "history": copy.deepcopy(history), "target": target}
        if index < len(calls):
            history.append({"action": target, "result": copy.deepcopy(results[index])})


def normalized(text):
    return re.sub(r"\d+", "#", " ".join(re.findall(r"\w+", text.casefold(), re.UNICODE)))


def group_requests(rows, threshold=0.85):
    """Conservative lexical near-duplicate components, not a semantic guarantee."""
    texts = [normalized(x["audio_text"]) for x in rows]
    parent = list(range(len(rows)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    postings = defaultdict(list)
    for i, text in enumerate(texts):
        words = set(text.split())
        candidates = set()
        for word in words:
            candidates.update(postings[word])
        for j in candidates:
            other = texts[j]
            if 2 * min(len(text), len(other)) < threshold * (len(text) + len(other)):
                continue
            matcher = SequenceMatcher(None, text, other, autojunk=False)
            if matcher.quick_ratio() >= threshold and matcher.ratio() >= threshold:
                a, b = root(i), root(j)
                parent[a] = b
        for word in words:
            postings[word].append(i)
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        groups[root(i)].append(row["id"])
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])


def split_groups(groups, reserved=(), seed=20261029, fraction=0.2):
    excluded, eligible = [], []
    for group in groups:
        (excluded if set(group) & set(reserved) else eligible).append(group)
    random.Random(seed).shuffle(eligible)
    target = round(sum(map(len, eligible)) * fraction)
    validation, train = [], []
    for group in eligible:
        (validation if len(validation) < target else train).extend(group)
    return {"train": sorted(train), "validation": sorted(validation),
            "excluded": sorted(x for g in excluded for x in g)}


def features(text, history, use_history=True):
    words = re.findall(r"\w+", text.casefold(), re.UNICODE)
    out = Counter("w:" + word for word in words)
    normalized_text = " ".join(words)
    out.update("c:" + normalized_text[i:i+3] for i in range(max(0, len(normalized_text)-2)))
    if use_history:
        steps = [s for s in history if isinstance(s, dict) and isinstance(s.get("action"), dict)]
        out["steps:" + str(min(len(steps), 6))] += 5
        for step in steps:
            out["called:" + str(step["action"].get("name"))] += 5
        if steps:
            out["last:" + str(steps[-1]["action"].get("name"))] += 5
            # Only observations already in the supplied prefix are used.
            obs = json.dumps(steps[-1].get("result", {}), ensure_ascii=False).casefold()
            out.update("obs:" + w for w in re.findall(r"\w+", obs, re.UNICODE))
    return out


class ActionRanker:
    """Multinomial NB diagnostic. It predicts names, not executable arguments."""
    def __init__(self, use_history=True):
        self.use_history = use_history
        self.counts = defaultdict(Counter)
        self.docs = Counter()
        self.vocabulary = set()

    def fit(self, examples):
        for example in examples:
            target = example["target"]
            label = target["name"] if target["type"] == "call" else FINISH
            self.docs[label] += 1
            fs = features(example["text"], example["history"], self.use_history)
            self.counts[label].update(fs)
            self.vocabulary.update(fs)
        return self

    def rank(self, text, history, available):
        fs = features(text, history, self.use_history)
        scores = {}
        for label, n in self.docs.items():
            if label != FINISH and label not in available:
                continue
            count = self.counts[label]
            denom = sum(count.values()) + len(self.vocabulary)
            scores[label] = math.log(n / sum(self.docs.values())) + sum(
                v * math.log((count.get(k, 0) + 1) / denom)
                for k, v in fs.items() if k in self.vocabulary)
        return sorted(scores, key=lambda label: (-scores[label], label))
