"""The practice sentences are shown to school children: keep the bank clean.

The blocklist covers clearly unsuitable topics (sexual content, profanity,
self-harm, drugs, alcohol, tobacco, violence and weapons, hate, gambling),
sentences about the Tatoeba project itself, and the topics that were removed
after review because they depend on context (death, war, fighting, crime,
religion, politics, romance, insults, bars and knives, foreigners). CI fails
if any sentence matches; a new sentence that needs one of these words has to
be discussed first.
"""
import csv
import re

import pytest

import validation

BLOCKLIST = {
    'sexual': r"sex|sexual\w*|sexy|naked|nude\w*|rap(?:e|ed|es|ing|ist\w*)|prostitut\w*|porn\w*|condom\w*|orgasm\w*"
              r"|erotic\w*|horny|masturbat\w*|whore\w*|slut\w*|brothel\w*|stripper\w*",
    'profanity': r"fuck\w*|shit\w*|bitch\w*|bastard\w*|asshole\w*|dickhead\w*|pussy|crap\w*|damn\w*|goddamn\w*|piss\w*"
                 r"|bollocks|bugger\w*|wtf",
    'self_harm': r"suicid\w*|overdos\w*|kill(?:ed|ing|s)? (?:my|him|her|them|your|our)sel(?:f|ves)"
                 r"|hang(?:ed)? (?:my|him|her)self|slit (?:my|his|her) wrists?",
    'drugs': r"drugs?|drugged|cocaine|heroin|marijuana|cannabis|meth|lsd|ecstasy|opium|narcotic\w*|junkie\w*",
    'alcohol': r"drunk\w*|beers?|wines?|vodka|whisk(?:e)?y|champagne|booze\w*|alcohol\w*|liquor\w*|rum|tequila|brandy"
               r"|cocktails?|hangovers?|sake|bartender\w*",
    'tobacco': r"cigarettes?|cigars?|tobacco|smoking|smokers?|smokes",
    'violence': r"kill|kills|killed|killing|killer\w*|murder\w*|guns?|gunman|gunmen|shoot\w*"
                r"|shot (?:him|her|them|me|you|us|dead|himself|herself)|stab(?:s|bed|bing|ber\w*)?"
                r"|bomb(?:s|ed|ing|er|ers)?|terroris\w*|massacre\w*|corpse\w*|tortur\w*|assassin\w*|strangl\w*"
                r"|hostage\w*|kidnap\w*|weapons?|rifles?|pistols?|bullets?|behead\w*|slaughter\w*",
    'hate': r"hitler|nazi\w*|racis\w*|kkk",
    'gambling': r"gambl\w*|casinos?|poker",
    'meta': r"tatoeba|toki pona|zamenhof",
    # Removed after review (context-dependent topics).
    'death': r"die|dies|died|dying|dead|death\w*|funeral\w*|grave\w*",
    'war_army': r"wars?|soldiers?|army|armies|battle\w*|military",
    'fighting': r"fight\w*|punch\w*|slap\w*|beat (?:him|her|them|me|you|us|up)|hit (?:him|her|them|me)",
    'crime': r"prison\w*|jail\w*|arrest\w*|crimes?|criminal\w*|steal\w*|stole|stolen|thie(?:f|ves)|rob|robbed"
             r"|robber\w*|police\w*",
    'religion': r"god|gods|jesus|christ|church\w*|bible\w*|pray\w*|muslims?|islam\w*|jews?|jewish|christian\w*"
                r"|buddhis\w*|allah|satan|devil\w*|hell",
    'politics': r"politic\w*|elections?|protest\w*|revolution\w*|communis\w*|dictator\w*|presidents?",
    'romance': r"kiss\w*|lovers?|affair\w*|divorc\w*|pregnan\w*|seduc\w*|cheat\w*|flirt\w*|marry me|wedding night",
    'insults': r"stupid\w*|idiot\w*|moron\w*|ugly|hate|hates|hated",
    'bars_knives': r"weed|stoned|smoke|smoked|bar|bars|pub|pubs|lottery|bet|bets|betting|knife|knives|poison\w*",
    'foreigners': r"foreigners?|immigrants?",
}
_PATTERNS = {name: re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE) for name, pattern in BLOCKLIST.items()}


@pytest.fixture(scope='module')
def sentences():
    with open('databases/data_en.csv', encoding='utf-8') as f:
        rows = list(csv.reader(f, delimiter=';'))
    assert rows[0] == ['sentence']
    return [row[0] for row in rows[1:]]


def test_no_sentence_matches_the_blocklist(sentences):
    hits = [(name, sentence) for sentence in sentences
            for name, pattern in _PATTERNS.items() if pattern.search(sentence)]
    assert not hits, f'{len(hits)} unsuitable sentences, e.g. {hits[:5]}'


def test_no_duplicate_sentences(sentences):
    seen, duplicates = set(), []
    for sentence in sentences:
        key = validation.normalize_text(sentence).lower()
        if key in seen:
            duplicates.append(sentence)
        seen.add(key)
    assert not duplicates, f'{len(duplicates)} duplicates, e.g. {duplicates[:5]}'


def test_every_level_still_has_sentences(sentences):
    import lambdaGetSample
    counts = {1: 0, 2: 0, 3: 0}
    for sentence in sentences:
        counts[lambdaGetSample.getSentenceCategory(validation.normalize_text(sentence))] += 1
    assert min(counts.values()) >= 50, counts
