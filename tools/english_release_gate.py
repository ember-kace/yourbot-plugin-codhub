"""Fail-closed English release gate for the pinned MW4 production scope.

This validates evidence declarations; it cannot authenticate a capture or infer
the language of arbitrary proper nouns. No asset class is implicitly exempt.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

ACCEPTED_QUALITIES = frozenset({"user_capture", "published_fixture", "native_localization", "official_reference"})
EXPECTED_ASSETS = 1267
EXPECTED_REFERENCES = 35
EXPECTED_ASSET_IDS_SHA256 = '64694bfac1bc0a8aaafb8fa5d4a3ee9efb3bc7490e546852cc0af3a947b6398a'
EXPECTED_REFERENCE_IDS_SHA256 = "5c192a08ef771757e1630b65fd5c4395e5e99938b3c7ec5658f2028ecf8c98ff"
EXPECTED_NATIVE_IDENTITY_SHA256 = 'f470195f02ef367d319537d2a035d0cdbfdd0185a9abeae88ab8540cd970807d'
MAX_JSON_BYTES = 32 * 1024 * 1024
_ID = re.compile(r"[0-9a-f]{16}\Z")
_PLACEHOLDER = re.compile(r"\b(?:untranslated|unresolved|uncatalogued|unknown|placeholder|todo|tbd|null|undefined)\b", re.I)

# The reviewed technical-description exception is intentionally separate from
# accepted player-facing name qualities. Its exact scope/proofs are pinned here.
INTERNAL_DESCRIPTION_SOURCE_ID = "reviewed-internal-descriptions-2026-11-09"
EXPECTED_INTERNAL_POLICY_SHA256 = "c6242d8c49e0fada0c61c168bcf809786c6e389e8657ac69649eab18a1b10f8b"
EXPECTED_INTERNAL_IDS_SHA256 = "afbc05fafed513e8a673ea2061367c0f38109914d302781e957918a14ab6c428"
EXPECTED_INTERNAL_REVIEW_SHA256 = "2c3d64b1e22d1209b74b0b551b2263ebe39d2eeabc119a21f6185cf6acd7908d"
EXPECTED_INTERNAL_SOURCE_SHA256 = "a8abe7b3faefa89d2bf4c4cfddc9096cf7daf109f47fb228e43770ed7f38e593"
EXPECTED_INTERNAL_RECORD_HASHES_SHA256 = "1b8de16d1c4e38d1b089da44733f3366ad764175e52858a77e468fdc91ea1c7e"
INTERNAL_DESCRIPTION_RECORD_HASHES = {
    "0018162cba4edcc8": "94e97a35cfb58ce8f4c4444192d600fd7a8944f07bfc6c159e72803033d8dcbb",
    "01fc874357ea00a6": "ff99c705b8058e2967cebbf2e1d70e6fe501d268e6713a4fbb0ebd63c0784ee7",
    "0228aeb2b9cee992": "2bb923a5a04fdc872f08c8317da278fedd972af06932cdfde4c37c9481b1d0a4",
    "06da833464bae609": "bb5bc5feff40f3cc7bf53301559d97e3294acfc1e314f5314c4f64adee87f1c7",
    "08e6d16a87a5f59d": "7b2a44b7daa49b9c0c26459b9aa17f7bc27e3f9b54a464f2579e00818bd27147",
    "09758be9c149c604": "b1f5433877c4b8c035e8cf9b937441cfd419b36a99587fa9bada2ddeef65ac5b",
    "0f9af35e9c08d6a2": "14864e38b651a8c83bc2aaaae312deaad335a89f5e9021ead1c1666f6e2764d7",
    "103594464a18a5e8": "6b9c0f74978743e90731261df1140273d36d6a3e6844e08b524ec24c5eafb6ba",
    "1067bbe63a3ca74e": "bd4555d072ec54058e4bf221d16894b4f0633c2d5edee94b384fbe5a6bc1f6ed",
    "10d33356eb86c8c0": "92798f9d517f606a9215b082df3946e6bc2c5d3037a9f0bb4606b34ec0ca89a0",
    "114cfb716b0dee1a": "6a03e1a647665bd0615b46193e8cd9cfd98dcda9a64dbb86907633d5e14ecbe8",
    "11c371364cdc1d13": "0ab72e39d714f4cb9ae2be5408348143b040fa55f0ea4889f0ad3602562273b9",
    "145344f1b9602a0f": "3e56436ca481ce18c837be9cac2ba30169e94afc02f65e83237ebc279224a3f9",
    "15d25dac1bf0b96f": "9b0dcd8232a987116a943febb5d3e669ba67ac3e67cb77142035768b0cf31feb",
    "17bd845f1a26323f": "9290b9b9c8ba59c8004da471df3249dd5e77e6bd9ab133f76e192d1c254e4cd1",
    "18795588987e8773": "2a100d5b3ca4e04ded50ec98558bae02d852a82b584eaf7054b9c1dbefeec532",
    "1cf58583fa1798ca": "fd3b4dbf75cc7180d7539223c8c730f23291938199b9b34dbba85a0db6fedbf0",
    "1f246ee65f99cf20": "b8c2e20e624699449aa872a21d4d1e7dceac1c1f24b6d855caf2f29c640949ee",
    "207962cbbe3a8d36": "8c13cc795c21b8bd65d4d39cabfd4bb698e819123c4c8f021658233b9651f8e7",
    "2101bfad74f6f3c9": "fcbe32f72aceeeb4969c6b1eedddffe65189d9f499768d7714b82f4f6e7b6a06",
    "2269fbecbf18b9ed": "571f2a8ad433c1e6bd48dca28fc5daee719a530e9d6ba274b3a23fcab771dcd8",
    "22af75fb5b56473f": "a1d373dbc8b3ea05fbbe5f504f747c30f9ebe7696e2aec7b26ef578f28d0645c",
    "22d70848e61c2f0c": "d81cb745bcf7297f81ba5c0d1a6ea431e3dd09b956e5cf086be07b471efa908f",
    "241fba411583575a": "3f13ec53c5805eda9eb9d613e9f97ba7e04ac59b2d08191d3abb857fd59a0857",
    "2b6e117e98d3733f": "dc2e4b855788967803d7bd0e59f8c227e896019c8090bf8a21c6912c1e73d5a9",
    "2c4563450670827a": "0dc6f80069e533ebe3e68d504667ee3f171df2f801a1298e155a46f2049eb251",
    "2e434d4937105092": "9a897b52eccc53b729a8f9ba720a72eb01f761646d06f4d641165519f8117093",
    "2e9ad42c82f3c7c0": "daadcca5ecbd9355830cb8396934bbe49e9e2961179bca1578fbf921d75262da",
    "31c7b6b6428d213c": "9a2f1e2057a5d627a24ef90c14b8a75b3932c8a4530ebbf182c7182245ddac4a",
    "31e0b5a45f33ce01": "0f50efb504a018e503cab3454e1a7f0084b17cbb8a1ce399afbb84d08d298900",
    "348dd7727c72982d": "095b045ce3d6ad5085bf768f173546048cb8c8ea072265bc2e9cde973d0a92c9",
    "364ab8104d3b600c": "7248e2547192513b48e8aa22618d01b07c6a7e89d9695a8e3dbf25684c76bc2b",
    "36d4079caf8b45b5": "614a82f427717eb3db3b8a46fe05089dc3ee68be9d71d37eb8ca3306d2918d52",
    "3783b227d98da33e": "8e2c3b4aea4febddab8b0708a10d949f633e6ce50e36da372c4bf16b67e81310",
    "385b80168aedffc5": "38334e43e3a822662554453f8011b114b282304acc89d77bd9de7c9647f43457",
    "3b888d4b50e96673": "0acd4af231427a0d8dd568c1ff04b4fb871c5d0c843f8036c11f704c660d523d",
    "3b95e40068e0cd6a": "0ffaaf8f5fc9d74eae7eaf1e233d84daea9f455c8042ed02187d02b5c816537b",
    "3f732ce2e265eec9": "70f30160a599f0c509679e51f761c4acbc9fa6b31995b6441d8d42c413978733",
    "40476f68dd7c6f0b": "d1edd1d95c2be45efe4f59d74c4c7eca9d253c9a8ff497b9fc97c64d6120c3bb",
    "40ab0083a34096ea": "2bd0bd19320ed1a2970bf0af16b0ecb30a0999df5f5414a9eeb134bbda435cc9",
    "414345d9cb6e56be": "15154ec2cf4dfdec9a008bef82edd1bd9295f7fcf9e45d54b228392ec66ae473",
    "4233511a8264b377": "36c682adbed3bddcabb6201a8f567385c39ea50407da00c6b68538cb3e4dd027",
    "434c692ce1b00d5c": "601c599878b5b73d724032c229bbcc7bf3dfc583bfca907b03a9d112e217ca59",
    "46b9be9836e937db": "704ab3ebaa457f88848e256d4e0c7cf74ff637bf29dc37e29dcbcdc9aa14aa26",
    "4814687c3c3cae09": "4ddefb8033fe207d088bab031eb636ece24087dabe93521d40e8293a4c7fe411",
    "484664b9876dce3e": "08db3f1c4c2d14cb0ea558465a39183e23b77e95aa8f08d8ede1b8be2fcace68",
    "49b8a977752b5cc5": "e9e19ed09a24551d15ac7a1a1e98a0cc2bf4fc829d1e02c7213ab425411b8059",
    "4fdc37f0da4d2c3c": "d6746e64493f4faeb07ed161ec9b7e53ed260d318d34dfafaaeaf334e9fe51ef",
    "526972b25eb16781": "a64adc73e73a1f43e4fd0072e7658da52da5de9dc005645ec9b21388db05f7b5",
    "54e48c9d7e4c508f": "36f8d518e719ca4951aab371f4203de9128e635c5592d88d38eaed3959c353c3",
    "54e48d9d7e4c5242": "139bff20f965039e6857c837acb783bf1cdb9154ac085e00583ed912e7583206",
    "55c4ca3b3028e4b2": "a5bcc48da92eecde58efb6ca635431d21024e0ba6d1aba55dad3cc3e7c6e81ba",
    "5acd02cc0843ac83": "7d03d07642563c7e4d79dd203d9b0993157323dfcbd9e189c8c4f290a2179d86",
    "5b689416e6d976ca": "d1cccbe45e96229e91e39a7226a4a445a2d1121c6405cae744a09a90456c947f",
    "5c25a49c26fbb600": "d5fe5609ca363a7be69786095a86b75ea65147ad202a4d204163ca552226853c",
    "5c59a40d25ce88d4": "32733e255b878dd9ac8e557210478f264620843e2b7c31d10bf2f3b548448617",
    "5cecc23577494031": "eeb00d836891857039e4fbd60681a736af7b0990b6459ec1a1c407a595124bd5",
    "60d87b27f81d7458": "e4d007e59dcb863c612a024235527e8887a76ccfa89b41eb76ac33f6eb6085a2",
    "660fcdf24aca86a6": "a9cd54b1382e3c2c9ded547b7391fcb5ce60c0d8f14c8114fcaf1930cb4cc4f3",
    "6747dc7df498343b": "42044baeaff5907546f01a7d81908481a21e13e515389c694d8cc1ea51fae007",
    "67c8bfa5cc4c4dd1": "2d95b2128e07feafd8da0a49f69fbd36606209814b5b9f93f35f70e1485de178",
    "68840e398c882dcf": "07be3b34d9d15db0ab1d30f0a164fe2a80277a9e2a0eb917c0149ed993aebf63",
    "6980e441febbc744": "4f91707e6ec7b79714873078c10d507104fe289f65dfae877e9adc1d5fe4f82b",
    "6b701a29f3e36776": "027dfe68f6c764cd31077527b3969942036758552918eb3ecdd79b07e2d1fa45",
    "6cda80d968379cca": "cd628d4d9cd735e6772e6555128886e7d348b965682edb9690b37b03e377bde3",
    "6e91a0b1c9fb22ba": "dbe040ddde9c097d8f1a635a4e700f11311a4281d805f1b56fb84bf2cf1623f0",
    "7580076752e5b3b4": "81bf98e8e4299e62043d589594be556c7a828f41acfce9a9d810132cf1c120e3",
    "771cd47fa148b721": "121d478dd4621eb7be7bbd42e24cfdf64b77db41dbaacb364a389fe2c98d16d5",
    "78cf2559999910fe": "b1740bf36569911b06cd4674675acc01a4ed0f8d8475e85570721266fca7c941",
    "7be8a6721b6d80a6": "014c77aa52b98f3120eb6f14353170dbd8db77dedeca1843c56456a26f0ee792",
    "7e43654da8ac730b": "d8f876d7968d21b2d1bc24819dd8517570cd09fdd66550661b6e08c804b5bc42",
    "7ebadba55ee81a20": "565a3f3eb9a0357cd2b554f90dc505aa2613d0b2b1c9a98dbac2ce590090200d"
}
INTERNAL_DESCRIPTION_BASE_KEYS = ("name", "quality", "kind", "internal_ref", "loot_id",
                                  "aliases", "source_ids", "name_claims", "name_ambiguous")

# A second, independently approved scope. These captions are never real names
# and do not alter the original72 review, objects or accepted name qualities.
TECHNICAL_DESCRIPTION_SOURCE_ID = "reviewed-technical-descriptions-2026-11-09"
EXPECTED_TECHNICAL_IDS_SHA256 = "0d176fcb55552685f68d8715d97ed045d93606e685eb35df561e6b17ee65c652"
EXPECTED_TECHNICAL_POLICY_SHA256 = "2dbf7f6f36526587f546be44708de60381f9671c75e7ab1cb6fd596a8e03352e"
EXPECTED_TECHNICAL_REVIEW_SHA256 = "b83099465f7c22396363a9b6e5fd07f27d7e64b1a3f1914da014d716d15d2dc9"
EXPECTED_TECHNICAL_SOURCE_SHA256 = "92910c52044cf8fd5b383e06bb9bdbeb2f23c744e09ac66394fcd81a6acd395f"
EXPECTED_TECHNICAL_RECORD_HASHES_SHA256 = "523678cfe5d545a131f60ecb9cf0ea44d8fcb7f073edc1cd755254f1688aee82"
TECHNICAL_DESCRIPTION_RECORD_HASHES = {
    "082948453ab4d9e3": "fc5542475d8571390e454ccabf4e0ea9376749b210c877866b9154f4b3cbb195",
    "0f8717576adcedb5": "03aff68ddfcb1b0daf50de7ff31b8a27710afebb685bc8709dd6893ae2e00d37",
    "110091e80861c775": "2a005c7a238e358c46189746669e7b8fad40b5fd8e7f44d4b68c59d69fe90dc8",
    "1e7b5b0fc5497fbe": "408a35106fde66cb2782c27ff01d6eb7ad067ae0cded72428b532173c899a992",
    "252f48bbd0918446": "71220c497d4a6bc764b129f8db59df498526ebb97b47532b546858b9044cb79c",
    "409a40a9e315c521": "7100c4a8c5ec367e30b12322be231c835b97080685cc48033990e7fe46addbf8",
    "427899df06f61aac": "bd577971707c524bf25bf3aab4a629a3a013ab68df646dd7cef31488e39695c9",
    "456f6831d04ffc02": "8dbe522f2f515e64b9458b7e44930fbf9eb48c02d3812c177fbdf8f6b5e2b7ae",
    "4d268a4bccd417d0": "31c3e050909f486c73788cd4a7a371bffba07cae6289a4676e69e16c6dccc634",
    "57cdf8fd235aa7b4": "b58e0d769eb6d045b333ff8947f8d9b35122bd38fa7f7bac10c5ff20710a8be9",
    "67f19c6bad5b1c0d": "60ef9d6451891d7f606dac4d2830889a055ac61757317a8dbba193b13862d801"
}
TECHNICAL_DESCRIPTION_BASE_KEYS = ("name", "quality", "kind", "internal_ref", "loot_id",
                                   "aliases", "source_ids", "name_claims", "name_ambiguous")


def canonical_digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                     allow_nan=False).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _internal_description_issues(asset_id, record, sources):
    """Cover only an exact approved hidden-record description; never rename it."""
    identifier = "asset:" + asset_id
    def issue(code, detail):
        return [{"id": identifier, "code": code, "detail": detail}]
    if asset_id not in INTERNAL_DESCRIPTION_RECORD_HASHES:
        return issue("internal_description_scope", "Technical descriptions are not approved for this required identity.")
    if (len(INTERNAL_DESCRIPTION_RECORD_HASHES) != 72
            or ids_digest(INTERNAL_DESCRIPTION_RECORD_HASHES) != EXPECTED_INTERNAL_IDS_SHA256
            or canonical_digest(INTERNAL_DESCRIPTION_RECORD_HASHES) != EXPECTED_INTERNAL_RECORD_HASHES_SHA256):
        return issue("internal_description_policy", "The pinned technical-description approval scope changed.")
    description = record.get("internal_description")
    if (not isinstance(description, dict) or description.get("quality") != "reviewed_internal_description"
            or description.get("language") != "en"
            or description.get("source_id") != INTERNAL_DESCRIPTION_SOURCE_ID
            or not valid_date(description.get("source_date"))
            or not isinstance(description.get("text"), str)
            or not description["text"].startswith("Internal · ")):
        return issue("invalid_internal_description", "A marked English technical description with reviewed provenance is required.")
    source = sources.get(INTERNAL_DESCRIPTION_SOURCE_ID)
    try:
        source_digest = canonical_digest(source)
        projection = {"base": {key: record.get(key) for key in INTERNAL_DESCRIPTION_BASE_KEYS},
                      "internal_description": description}
        record_digest = canonical_digest(projection)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return issue("invalid_internal_description", "Description evidence is not a canonical reviewed JSON record.")
    if (source_digest != EXPECTED_INTERNAL_SOURCE_SHA256
            or not isinstance(source, dict) or source.get("input_sha256") != EXPECTED_INTERNAL_REVIEW_SHA256):
        return issue("internal_description_provenance", "The exact approved technical-description source and policy are required.")
    if record_digest != INTERNAL_DESCRIPTION_RECORD_HASHES[asset_id]:
        return issue("internal_description_review_changed", "Name identity, technical description or evidence differs from the exact approved review.")
    return []


def _technical_description_issues(asset_id, record, sources):
    """Cover only the eleven explicitly approved captions, including P01."""
    identifier = "asset:" + asset_id
    def issue(code, detail):
        return [{"id": identifier, "code": code, "detail": detail}]
    if asset_id not in TECHNICAL_DESCRIPTION_RECORD_HASHES:
        return issue("technical_description_scope", "Technical captions are not approved for this required identity.")
    original_sources = record.get("source_ids")
    if (not isinstance(original_sources, list) or not original_sources
            or any(not isinstance(key, str) or not isinstance(sources.get(key), dict)
                   or not isinstance(sources[key].get("title"), str) or not sources[key]["title"].strip()
                   or not valid_date(sources[key].get("source_date")) for key in original_sources)):
        return issue("technical_description_original_provenance", "The original registered source declarations must remain structurally valid.")
    if (len(TECHNICAL_DESCRIPTION_RECORD_HASHES) != 11
            or ids_digest(TECHNICAL_DESCRIPTION_RECORD_HASHES) != EXPECTED_TECHNICAL_IDS_SHA256
            or canonical_digest(TECHNICAL_DESCRIPTION_RECORD_HASHES) != EXPECTED_TECHNICAL_RECORD_HASHES_SHA256
            or set(TECHNICAL_DESCRIPTION_RECORD_HASHES) & set(INTERNAL_DESCRIPTION_RECORD_HASHES)):
        return issue("technical_description_policy", "The pinned eleven-caption approval scope changed.")
    description = record.get("technical_description")
    if (not isinstance(description, dict) or description.get("quality") != "reviewed_technical_description"
            or description.get("language") != "en" or description.get("source_id") != TECHNICAL_DESCRIPTION_SOURCE_ID
            or description.get("source_date") != "2026-11-09"
            or not isinstance(description.get("text"), str) or not description["text"].startswith("Technical record \u00b7 ")):
        return issue("invalid_technical_description", "An explicitly reviewed, marked English technical caption is required.")
    source = sources.get(TECHNICAL_DESCRIPTION_SOURCE_ID)
    try:
        source_digest = canonical_digest(source)
        projection = {"base": {key: record.get(key) for key in TECHNICAL_DESCRIPTION_BASE_KEYS},
                      "technical_description": description}
        record_digest = canonical_digest(projection)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return issue("invalid_technical_description", "Caption evidence is not canonical reviewed JSON.")
    if (source_digest != EXPECTED_TECHNICAL_SOURCE_SHA256 or not isinstance(source, dict)
            or source.get("input_sha256") != EXPECTED_TECHNICAL_REVIEW_SHA256
            or source.get("policy_sha256") != EXPECTED_TECHNICAL_POLICY_SHA256):
        return issue("technical_description_provenance", "The exact reviewed policy and source evidence are required.")
    if record_digest != TECHNICAL_DESCRIPTION_RECORD_HASHES[asset_id]:
        return issue("technical_description_review_changed", "Original identity/name evidence or the approved caption/proof changed.")
    return []


def label_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _word_key(value):
    return re.sub(r"[^a-z0-9]", "", label_key(value))


def readable_name_issue(value, record=None):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        return "Name must be nonempty text of at most 160 characters."
    if any(unicodedata.category(c).startswith("C") or unicodedata.category(c) in {"Zl", "Zp"} for c in value):
        return "Name contains control, invisible format or line-separator characters."
    if not re.search(r"[A-Za-z]", value) or _PLACEHOLDER.search(value):
        return "Name is missing readable English text or contains a placeholder marker."
    if "_" in value or re.fullmatch(r"(?:0x)?[0-9a-fA-F]{8,}", value.strip()):
        return "Name is an internal identifier or hash."
    if "^" in value or value.lstrip().startswith("#PH:"):
        return "Name contains unresolved game formatting or a native placeholder key."
    if re.search(r"\b(?:weapon|attachment|slot)\s*(?:ID\s*)?\d+\s*$", value, re.I):
        return "Name is a numbered fallback label."
    if record:
        internal = record.get("internal_ref")
        if isinstance(internal, str) and internal:
            parts = internal.split("_")
            if parts[0] in {"rex", "iw9", "jup", "t10", "t11"}:
                parts = parts[1:]
            if record.get("kind") == "weapon" and parts and parts[0] in {"ar", "br", "dm", "la", "lm", "me", "pi", "sh", "sm", "sn", "misc"}:
                parts = parts[1:]
            if _word_key(value) in {_word_key(internal), _word_key(" ".join(parts))}:
                return "Name is the internal reference rendered as words."
    return None


def valid_date(value):
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def ids_digest(ids):
    return hashlib.sha256(("\n".join(sorted(ids)) + "\n").encode("ascii")).hexdigest()


def native_identity_digest(weapons):
    """Pin identities and reserved positions independently of English labels."""
    if not isinstance(weapons, dict):
        raise ValueError("Native weapon map must be an object.")
    projection = {}
    for prefix, weapon in weapons.items():
        if not isinstance(weapon, dict) or not isinstance(weapon.get("slots"), dict):
            raise ValueError("Native weapon and slot maps must be objects.")
        row = {key: weapon.get(key) for key in ["asset_id", "metadata_locked", "native_supported", "utility"]}
        row["slots"] = {}
        for slot, group in weapon["slots"].items():
            if not isinstance(group, dict) or not isinstance(group.get("ids"), dict):
                raise ValueError("Native slot identity maps must be objects.")
            row["slots"][slot] = {"declared_positions": group.get("declared_positions"),
                                  "reserved_ids": group.get("reserved_ids"), "ids": {}}
            for number, selected in group["ids"].items():
                if not isinstance(selected, dict):
                    raise ValueError("Native item identity records must be objects.")
                row["slots"][slot]["ids"][number] = {key: selected.get(key) for key in ["asset_id", "metadata_locked"]}
        projection[prefix] = row
    raw = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON file exceeds the 32 MiB bound.")
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8"), parse_constant=lambda v: (_ for _ in ()).throw(ValueError("Non-finite JSON number: " + v)))


def _source_ok(source, quality):
    if not isinstance(source, dict) or not isinstance(source.get("title"), str) or not source["title"].strip() or not valid_date(source.get("source_date")):
        return False
    allowed = {quality}
    if quality == "published_fixture":
        allowed.add("published_launch_snapshot")
    if source.get("kind") not in allowed:
        return False
    if source.get("language") not in (None, "en"):
        return False
    if quality in {"official_reference", "published_fixture"}:
        try:
            url = urlsplit(source.get("url", ""))
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                return False
        except (ValueError, TypeError):
            return False
    if quality == "native_localization":
        return source.get("language") == "en" and bool(re.fullmatch(r"[0-9a-f]{64}", str(source.get("input_sha256") or source.get("sha256") or "")))
    return True


def _record_issues(identifier, record, sources):
    result = []
    def add(code, detail):
        result.append({"id": identifier, "code": code, "detail": detail})
    if not isinstance(record, dict):
        add("invalid_record", "Required record is not an object.")
        return result
    quality = record.get("quality")
    if quality not in ACCEPTED_QUALITIES:
        add("untranslated_quality", "English name quality is not accepted: " + str(quality))
    name_error = readable_name_issue(record.get("name"), record)
    if name_error:
        add("unreadable_name", name_error)
    if record.get("name_ambiguous"):
        add("ambiguous_name", "Name has an unresolved ambiguity flag.")
    source_ids = record.get("source_ids")
    if not isinstance(source_ids, list) or not source_ids or any(not isinstance(s, str) or s not in sources for s in source_ids):
        add("invalid_source_refs", "Name must preserve references to registered sources.")
    elif quality in ACCEPTED_QUALITIES and not any(_source_ok(sources[s], quality) for s in source_ids):
        add("missing_name_provenance", "No matching name-quality source has a title, evidence date and English provenance.")
    if quality == "native_localization":
        claims = record.get("name_claims", [])
        if not isinstance(claims, list) or not any(
            isinstance(c, dict) and c.get("language") == "en" and c.get("quality") == quality
            and isinstance(c.get("name"), str) and label_key(c["name"]) == label_key(record.get("name") or "")
            and c.get("source_id") in sources and _source_ok(sources[c["source_id"]], quality)
            and c.get("source_date") == sources[c["source_id"]].get("source_date")
            for c in claims):
            add("missing_exact_name_claim", "Native localization needs an English claim linking this name to its source.")
    return result


def evaluate_documents(catalog, provenance):
    """Evaluate loaded documents without changing files (also used by dry runs)."""
    result = {"ready": False, "required": EXPECTED_ASSETS + EXPECTED_REFERENCES,
              "total_translated": 0, "total_described": 0, "total_english_covered": 0,
              "total_internal_described": 0, "total_technical_described": 0,
              "described_ids": [], "missing_ids": [], "issues": [], "snapshot_date": None,
              "accepted_qualities": sorted(ACCEPTED_QUALITIES), "counts": {"assets_required": EXPECTED_ASSETS, "reference_weapons_required": EXPECTED_REFERENCES}}
    issues = result["issues"]
    if not isinstance(catalog, dict) or not isinstance(provenance, dict):
        issues.append({"id": "catalog", "code": "invalid_documents", "detail": "Catalog and provenance must be JSON objects."})
        return result
    snapshot = catalog.get("snapshot")
    result["snapshot_date"] = snapshot.get("date") if isinstance(snapshot, dict) else None
    if not isinstance(snapshot, dict) or snapshot.get("game") != "mw4" or not valid_date(snapshot.get("date")) or provenance.get("snapshot_date") != snapshot.get("date"):
        issues.append({"id": "snapshot", "code": "invalid_snapshot_provenance", "detail": "MW4 snapshot and provenance dates must be present and agree."})
    assets = catalog.get("assets")
    references = catalog.get("reference_weapons")
    sources = provenance.get("sources")
    if not isinstance(assets, dict) or not isinstance(references, list) or not isinstance(sources, dict):
        issues.append({"id": "catalog", "code": "invalid_documents", "detail": "Missing assets, reference_weapons or registered sources."})
        return result
    asset_ids = list(assets)
    ref_ids = [r.get("asset_id") if isinstance(r, dict) else None for r in references]
    for scope, ids, expected_count, expected_digest in [
        ("assets", asset_ids, EXPECTED_ASSETS, EXPECTED_ASSET_IDS_SHA256),
        ("reference_weapons", ref_ids, EXPECTED_REFERENCES, EXPECTED_REFERENCE_IDS_SHA256),
    ]:
        valid_ids = all(isinstance(i, str) and _ID.fullmatch(i) for i in ids)
        result["counts"][scope + "_actual"] = len(ids)
        if len(ids) != expected_count or len(set(str(i) for i in ids)) != len(ids) or not valid_ids or ids_digest(ids) != expected_digest:
            issues.append({"id": scope, "code": "required_scope_changed", "detail": "Count or exact identity set differs from the pinned MW4 release scope. No implicit exclusions are allowed."})
    translated_assets = translated_references = described_assets = 0
    internal_described = technical_described = 0
    for asset_id, record in assets.items():
        found = _record_issues("asset:" + asset_id, record, sources)
        if not found:
            translated_assets += 1
            # A genuine verified name takes precedence and is counted once.
            # The exception must never spread to another named/selectable item.
            if isinstance(record, dict) and "internal_description" in record and asset_id not in INTERNAL_DESCRIPTION_RECORD_HASHES:
                issues.extend(_internal_description_issues(asset_id, record, sources))
            if isinstance(record, dict) and "technical_description" in record and asset_id not in TECHNICAL_DESCRIPTION_RECORD_HASHES:
                issues.extend(_technical_description_issues(asset_id, record, sources))
        elif isinstance(record, dict) and ("internal_description" in record or "technical_description" in record):
            description_issues = []
            if "internal_description" in record:
                description_issues.extend(_internal_description_issues(asset_id, record, sources))
            if "technical_description" in record:
                description_issues.extend(_technical_description_issues(asset_id, record, sources))
            # A reviewed description substitutes only for the absent readable
            # name. It cannot repair dangling original source refs, ambiguity,
            # malformed records or any future structural/provenance failure.
            blocking_name_issues = [issue for issue in found
                                    if issue["code"] not in {"untranslated_quality", "unreadable_name"}]
            if not description_issues and not blocking_name_issues:
                described_assets += 1
                internal_described += "internal_description" in record
                technical_described += "technical_description" in record
                result["described_ids"].append("asset:" + asset_id)
            else:
                issues.extend(found)
                issues.extend(description_issues)
        else:
            issues.extend(found)
    for index, reference in enumerate(references):
        asset_id = reference.get("asset_id") if isinstance(reference, dict) else None
        identifier = "reference:" + str(asset_id or index)
        found = _record_issues(identifier, reference, sources)
        if isinstance(reference, dict) and "internal_description" in reference:
            found.append({"id": identifier, "code": "internal_description_scope", "detail": "Reference weapons require verified names; technical descriptions do not cover them."})
        if isinstance(reference, dict) and "technical_description" in reference:
            found.append({"id": identifier, "code": "technical_description_scope", "detail": "Reference weapons require verified names; the eleven captions do not cover them."})
        if asset_id not in assets:
            found.append({"id": identifier, "code": "missing_asset", "detail": "Reference weapon has no production asset."})
        elif isinstance(reference, dict):
            asset = assets[asset_id]
            if not isinstance(asset, dict) or reference.get("name") != asset.get("name") or reference.get("quality") != asset.get("quality"):
                found.append({"id": identifier, "code": "reference_name_conflict", "detail": "Reference name/quality differs from its production asset."})
        issues.extend(found)
        translated_references += not found
    weapons = catalog.get("weapons")
    try:
        identity_digest = native_identity_digest(weapons)
    except (ValueError, TypeError):
        identity_digest = None
    if identity_digest != EXPECTED_NATIVE_IDENTITY_SHA256:
        issues.append({"id": "weapons", "code": "native_identity_scope_changed", "detail": "Native prefixes, weapon IDs/flags or slot/attachment IDs/reserved positions differ from the pinned production snapshot."})
    if not isinstance(weapons, dict):
        issues.append({"id": "weapons", "code": "invalid_identity_map", "detail": "Native weapon map is missing."})
    else:
        for prefix, weapon in weapons.items():
            if not isinstance(weapon, dict) or weapon.get("asset_id") not in assets:
                issues.append({"id": "weapon:" + str(prefix), "code": "missing_asset", "detail": "Native weapon points outside required assets."})
                continue
            slots = weapon.get("slots")
            if not isinstance(slots, dict):
                issues.append({"id": "weapon:" + str(prefix), "code": "invalid_identity_map", "detail": "Weapon slots are not an object."})
                continue
            for slot, table in slots.items():
                if not isinstance(table, dict) or not isinstance(table.get("ids"), dict):
                    issues.append({"id": "weapon:" + prefix, "code": "invalid_identity_map", "detail": "Invalid slot identity table."})
                    continue
                for number, selected in table["ids"].items():
                    if not isinstance(selected, dict) or selected.get("asset_id") not in assets:
                        issues.append({"id": f"selection:{prefix}:{slot}:{number}", "code": "missing_asset", "detail": "Selected item points outside required assets."})
    result["counts"].update({"assets_translated": translated_assets, "reference_weapons_translated": translated_references,
                            "assets_described": described_assets, "reference_weapons_described": 0,
                            "assets_internal_described": internal_described,
                            "assets_technical_described": technical_described,
                            "assets_english_covered": translated_assets + described_assets,
                            "reference_weapons_english_covered": translated_references})
    result["total_translated"] = translated_assets + translated_references
    result["total_described"] = described_assets
    result["total_internal_described"] = internal_described
    result["total_technical_described"] = technical_described
    result["total_english_covered"] = result["total_translated"] + described_assets
    result["missing_ids"] = sorted({i["id"] for i in issues if i["id"].startswith(("asset:", "reference:"))})
    result["ready"] = not issues and result["total_english_covered"] == result["required"]
    return result


def evaluate_release(plugin_path):
    data = Path(plugin_path) / "cod_hub/data"
    try:
        return evaluate_documents(read_json(data / "catalog.json"), read_json(data / "facts-sources.json"))
    except (OSError, ValueError, TypeError, AttributeError, KeyError, OverflowError) as error:
        return {"ready": False, "required": EXPECTED_ASSETS + EXPECTED_REFERENCES, "total_translated": 0,
                "total_described": 0, "total_english_covered": 0, "described_ids": [], "missing_ids": [],
                "total_internal_described": 0, "total_technical_described": 0,
                "issues": [{"id": "catalog", "code": "unreadable_documents", "detail": str(error)}], "counts": {}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, default=Path(__file__).resolve().parents[1] / "plugin")
    args = parser.parse_args(argv)
    report = evaluate_release(args.plugin)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
