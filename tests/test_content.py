"""The practice sentences are shown to school children: keep the bank clean.

The blocklist covers clearly unsuitable topics (sexual content, intimate
health questions, profanity, self-harm, drugs, alcohol, tobacco, violence and
weapons, hate, stereotypes, body shaming, gambling), sentences about the
Tatoeba project itself, and the topics that were removed after review because
they depend on context (death, war, fighting, crime, religion, politics,
romance, sexuality and gender identity, insults, bars and knives, foreigners).
CI fails if any sentence matches; a new sentence that needs one of these words
has to be discussed first.

A second review in 2026-11 read every sentence and removed 357 more, which the
keywords had missed ("Semen is worth bottling."). content_removed_en.tsv lists
them; CI fails if one comes back.

No sentence names a person (2026-11-17, the school's rule: "He is a student",
not "Tom is a student"). A sentence whose only names were at its very start
("Tom ...", "Tom and Mary ...") got the pronoun (He, She, They); every other
sentence with a name was removed. PERSON_NAMES lists the names, family names,
characters and titles the bank had; CI fails if one comes back. Places,
languages and days are not people and stay.
"""
import csv
import re
from pathlib import Path

import pytest

import validation

BLOCKLIST = {
    'sexual': r"sex|sexual\w*|sexy|sexier|sexiest|naked|nude\w*|rap(?:e|ed|es|ing|ist\w*)|prostitut\w*|porn\w*"
              r"|condom\w*|orgasm\w*|erotic\w*|horny|masturbat\w*|whore\w*|slut\w*|brothel\w*|stripper\w*"
              r"|semen|sperm\w*|penis\w*|vagina\w*|genital\w*|ejaculat\w*|breasts|boobs?|nipples?|testic\w*"
              r"|intercourse|crotch\w*|underwear|undress\w*|bras?|lingerie|panties|made love|make love|making love"
              r"|well-endowed|wet t-shirt|that's what she said|take (?:off )?(?:all of )?your clothes"
              r"|took off (?:her|his) clothes",
    'intimate_health': r"syphilis|gonorrh\w*|chlamydia|birth control|contracepti\w*|sanitary towels?|tampons?"
                       r"|menstrua\w*|urinat\w*|urinary|bladder infections?|bowel movements?|unusual discharge",
    'profanity': r"fuck\w*|shit\w*|bitch\w*|bastard\w*|asshole\w*|dickhead\w*|pussy|crap\w*|damn\w*|goddamn\w*|piss\w*"
                 r"|bollocks|bugger\w*|wtf",
    'self_harm': r"suicid\w*|overdos\w*|kill(?:ed|ing|s)? (?:my|him|her|them|your|our)sel(?:f|ves)"
                 r"|hang(?:ed)? (?:my|him|her)self|slit (?:my|his|her) wrists?",
    'drugs': r"drugs?|drugged|cocaine|heroin|marijuana|cannabis|meth|lsd|ecstasy|opium|narcotic\w*|junkie\w*"
             r"|painkillers?",
    'alcohol': r"drunk\w*|beers?|wines?|vodka|whisk(?:e)?y|champagne|booze\w*|alcohol\w*|liquor\w*|rum|tequila|brandy"
               r"|cocktails?|hangovers?|sake|bartender\w*|cognac|schnapps|radler|bud light|moscow mule|intoxicated"
               r"|corkscrews?|drinkers?|binge drink\w*|drinking problem|been drinking|stopped drinking|went drinking"
               r"|drinks heavily|drank too much|off the bottle|another drink|bought drinks|out for a drink"
               r"|buy me a drink|for a drink",
    'tobacco': r"cigarettes?|cigars?|tobacco|smoking|smokers?|smokes|ashtrays?",
    'violence': r"kill|kills|killed|killing|killer\w*|murder\w*|guns?|gunman|gunmen|shoot\w*"
                r"|shot (?:him|her|them|me|you|us|dead|himself|herself)|stab(?:s|bed|bing|ber\w*)?"
                r"|bomb(?:s|ed|ing|er|ers)?|terroris\w*|massacre\w*|corpse\w*|tortur\w*|assassin\w*|strangl\w*"
                r"|hostage\w*|kidnap\w*|weapons?|rifles?|pistols?|bullets?|behead\w*|slaughter\w*"
                r"|burn(?:ed|t) alive|attackers?|muggers?|mugg(?:ed|ing)|black and blue|crossbows?|revolvers?"
                r"|gunshots?|maced|assault\w*|wr(?:i|u)ng (?:\w+'s|the \w+'s|his|her) neck|black eye|bore arms"
                r"|beating (?:his|her|your|my) (?:wife|husband)|you(?:'ll| will) pay for",
    'hate': r"hitler|nazi\w*|racis\w*|kkk",
    'stereotypes': r"most beautiful (?:women|girls|woman|girl)|is (?:even )?more (?:beautiful|attractive|handsome) than"
                   r"|ideal women|(?:men|women|girls|boys|males|females) are (?:so|more|less|like|always)"
                   r"|because you're a girl|degrading to women|count your fingers|black guys|yellow or normal"
                   r"|hard to be a woman",
    'body_shaming': r"fat|fatter|fattest|overweight|go on a diet|losing weight",
    'gambling': r"gambl\w*|casinos?|poker",
    'meta': r"tatoeba|toki pona|zamenhof",
    # Removed after review (context-dependent topics).
    'death': r"die|dies|died|dying|dead|death\w*|funeral\w*|grave\w*|drown(?:s|ed|ing)?|passed away|rigor mortis"
             r"|miscarriage\w*|buried at sea|alive anymore|isn't alive|seen again alive|brain activity"
             r"|jumped out of the window",
    'war_army': r"wars?|soldiers?|army|armies|battle\w*|military|marines|troops|garrison\w*|captivity|militias?"
                r"|torpedo\w*|under attack",
    'fighting': r"fight\w*|punch\w*|slap\w*|beat (?:him|her|them|me|you|us|up)|hit (?:him|her|them|me)",
    'crime': r"prison\w*|jail\w*|arrest\w*|crimes?|criminal\w*|steal\w*|stole|stolen|thie(?:f|ves)|rob|robbed"
             r"|robber\w*|police\w*|convicted|convicts?|imprison\w*|handcuff\w*|paroled?|riots?|mafia|blackmailed"
             r"|cops|recaptured",
    'religion': r"god|gods|jesus|christ|church\w*|bible\w*|pray\w*|muslims?|islam\w*|jews?|jewish|christian\w*"
                r"|buddhis\w*|allah|satan|devil\w*|hell|popes?|priests?|sermons?|monaster\w*|convents?|chapel\w*"
                r"|mosques?|qur'?an|gospel\w*|catholic\w*|judaism|baptiz\w*|heathen\w*|exorcis\w*|sinned"
                r"|resurrection|pastors?|buddha\w*|religio\w*|passover|easter|eternal life|holy|verily|evil spirits?"
                r"|from heaven|heaven's",
    'politics': r"politic\w*|elections?|protest\w*|revolution\w*|communis\w*|dictator\w*|presidents?|socialis\w*"
                r"|conservatives?|liberals?|reactionar\w*|deport\w*|immigration|stalin|biden|marx\w*|feminis\w*"
                r"|democrats?|republicans?|inaugurat\w*|palestin\w*|founding fathers|censorship|corruption"
                r"|black lives matter|reparations|slave\w*|slavery|handguns?",
    'romance': r"kiss\w*|lovers?|affair\w*|divorc\w*|pregnan\w*|seduc\w*|cheat\w*|flirt\w*|marry me|wedding night"
               r"|infidelity|ex-husbands",
    'sexuality_gender': r"gay|gays|lesbian\w*|bisexual\w*|homosexual\w*|transgender\w*|trans (?:man|men|woman|women)"
                        r"|transmasculine|transfeminine",
    'insults': r"stupid\w*|idiot\w*|moron\w*|ugly|hate|hates|hated|hating|psychos?|chavs?|crippled|gypsy|gypsies"
               r"|mama's boy|shut up|untalented|detestable|get a life|never be loved|you sure do lie"
               r"|you(?:'re| are| must be)(?: just| such| very| really| so)*(?: a| an)?"
               r" (?:fool|coward|lazy|useless|mean person|liar)\w*",
    'bars_knives': r"weed|stoned|smoke|smoked|bar|bars|pub|pubs|lottery|bet|bets|betting|knife|knives|poison\w*"
                   r"|nightclubs?",
    'foreigners': r"foreigners?|immigrants?",
}
_PATTERNS = {name: re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE) for name, pattern in BLOCKLIST.items()}
REMOVED = Path(__file__).with_name('content_removed_en.tsv')

# Case-sensitive: "Bill", "Mark", "Miss" and "Brown" are names or titles only when capitalised.
PERSON_NAMES = re.compile(r"\b(?:" + '|'.join(sorted("""
    Akiko Albert Alekhine Alex Alice Allan Andersen Andy Angela Ania Anne Axel Barbie Bauer Beth Bill Bob
    Botwinnik Brown Bruno Capablanca Carlos Carmen Catherine Chabaud Charles Chewtarou Chizuru Cicero Dan
    Danican Darcy Darwin Diana Dickens Diderot Dima Diogenes Dr Einstein Ellen Emily Federer Fischer Foster
    Fran Frederick Gaga Galileo Garfield Garry Geiger George Giordano Gustav Hamlet Hanako Hansen Hashimoto
    Heidi Henry Hillary Holmes Horace Horus Jack Jackson Jacksons Jane Jeff Jeffrey Jenkins Jenny Jensen
    Jerzy Jill Jim John Jones Judit Judy Julius Juliet Karen Karima Kasparov Kate Keenan Ken Kenji Kepler
    Lana Laurie Layla Lee Leyla Lincoln Lisa Louis Lucy Madonna Magdalena Maharaj Maria Marie Marika Marilla
    Mario Mark Marlowe Mary Masao Mayuko Mecking Meier Melanie Merkel Michael Michelle Mike Miller Millers
    Ming Miss Mogami Mona Mr Mrs Ms Murphy Naoko Neubronner Neumanns Niamh Ogawa Olya Orwell Paul Paulo Pedro
    Peter Philidor Philip Pinocchio Pip Pizzaro Plato Prince Professor Rafael Rex Rin Roger Romeo Ron
    Sachiko Sakura Salima Sami Santa Sara Scott Seneca Seuss Shakespeare Shivaji Skura Slim Smith Sophie
    Spencer Spenser Steve Suzuki Tal Tanaka Tedros Thomas Tim Tom Tommy Tonya Trish Turner Weissman
    Xiangzhi Xiao Xiaoming Yamada Yanni Yoko Yoshida Yumi Yuriko Zsuzsa
""".split())) + r")\b")


def _key(sentence):
    return validation.normalize_text(sentence).lower()


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


def test_no_sentence_removed_after_review_comes_back(sentences):
    removed = {}
    for line in REMOVED.read_text(encoding='utf-8').splitlines():
        category, sentence = line.split('\t', 1)
        removed[_key(sentence)] = category
    assert len(removed) >= 350
    back = [(removed[_key(s)], s) for s in sentences if _key(s) in removed]
    assert not back, f'{len(back)} sentences removed after review are back, e.g. {back[:5]}'


def test_no_sentence_names_a_person(sentences):
    named = [s for s in sentences if PERSON_NAMES.search(s)]
    assert not named, f'{len(named)} sentences name a person, e.g. {named[:5]}'


def test_the_names_check_catches_the_bank_s_names():
    for sentence in ('Tom is a student.', 'Mr. Jackson is our math teacher.', 'Ask Bill.', "Yanni's car."):
        assert PERSON_NAMES.search(sentence), sentence
    for sentence in ('He is a student.', 'Pay the bill.', 'I miss you.', 'It is brown.', 'December 24th is Christmas Eve.'):
        assert not PERSON_NAMES.search(sentence), sentence


def test_the_blocklist_still_catches_the_first_finding():
    assert any(p.search('Semen is worth bottling.') for p in _PATTERNS.values())


def test_no_duplicate_sentences(sentences):
    seen, duplicates = set(), []
    for sentence in sentences:
        key = _key(sentence)
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
