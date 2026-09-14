"""Reviewed immutable reconciliation plans.

Each entry was compared with the archived PDF named by its SHA-256.  The plan
contains every currently observed relationship for the parent, then selects a
specific malformed relationship by ID.  Safe relationships are the explicit
reviewed remainder; no name-pattern selection occurs during execution.
"""

from __future__ import annotations

from .reconciliation import LegIdentity, ReconciliationPlan, RelayIdentity, RelayTarget


def _leg(
    leg_id: int,
    leg_number: int,
    swimmer_id: int,
    swimmer_name: str,
    age: int,
    gender: str | None,
    is_guest: bool,
    reaction_time: str | None,
) -> LegIdentity:
    return LegIdentity(
        leg_id,
        leg_number,
        swimmer_id,
        swimmer_name,
        age,
        gender,
        is_guest,
        reaction_time,
    )


def _target(
    relay_result_id: int,
    source_document_sha256: str,
    source_event_number: str,
    event: str,
    raw_team_name: str,
    relay_letter: str,
    result_time: str,
    observed: tuple[LegIdentity, ...],
    malformed_leg_id: int,
    content_hash: str,
) -> RelayTarget:
    return RelayTarget(
        parent=RelayIdentity(
            relay_result_id=relay_result_id,
            source_document_sha256=source_document_sha256,
            source_event_number=source_event_number,
            event=event,
            raw_team_name=raw_team_name,
            relay_letter=relay_letter,
            result_time=result_time,
            round="Final",
            content_hash=content_hash,
        ),
        expected_observed_count=len(observed),
        expected_observed_legs=observed,
        malformed_leg_ids=(malformed_leg_id,),
        expected_safe_legs=tuple(leg for leg in observed if leg.leg_id != malformed_leg_id),
    )


_JUNIOR_DAY_1 = "94826107b933cbb02be99ea6bfb4ad477a34e9f05b4593f34ec21cec319a6b95"
_JUNIOR_DAY_2 = "d3027392745bd96069e842ba88711b1c33130e4c8bec40309ed7ecc500f18a88"
_JUNIOR_DAY_3 = "f740fe6a016542a83db30538d452dc0f97c61096d8ae261daa6cd393d4872c50"
_SENIOR_DAY_1 = "b7853547e954de41ed0ba214f303abec070766c3b248e0ab46fa78ba28dd7c44"
_SENIOR_DAY_2 = "ebb2e4bd17f1a5279470c02c6168ffedb6ef9aee3389e6169215f73a622a264e"
_SENIOR_DAY_3 = "883b155a75521a9418c511907f0522c7278faf5a664390f7fc1d4079e557a7b5"
_SENIOR_DAY_4 = "3b652475a7bff283f20f26e289e0579a0e6e23c2015f4fd61d13e7114bf34bfc"
_SENIOR_DAY_5 = "31130eae788dc71e510e8e7b2df2011903f5447a95378c4082b5bc4698427dd7"
_SENIOR_DAY_6 = "74b96797499dd6a46dc8ce3ea6b4a0001374489d039d747b219551dffa17a1af"


SNAG_2026_MALFORMED_RELAY_LEGS = ReconciliationPlan(
    plan_id="snag-2026-malformed-relay-legs-v1",
    targets=(
        _target(
            28, _JUNIOR_DAY_1, "117", "Mixed 11-12 200 LC Meter Medley Relay",
            "Chinese Swimming Club S'Pore", "A", "2:10.59",
            (
                _leg(109, 1, 102, "Chan, Yi En Adelyn", 12, "W", False, "0.56"),
                _leg(110, 2, 632, "Teo, Cheng Jun Jaerus", 12, "M", False, "0.04"),
                _leg(111, 3, 64, "Lam, Mikayla Joan Xin Ya", 4, "W", False, "0.35"),
            ), 111, "4e7c2edee1aecabe68d7ada92e6ee368072af95ae72cc02c672ce97b1d952f5b",
        ),
        _target(
            29, _JUNIOR_DAY_1, "117", "Mixed 11-12 200 LC Meter Medley Relay",
            "Singapore Swimming Club", "A", "2:12.54",
            (
                _leg(112, 1, 99, "Lim, En Xuan Diane", 12, "W", False, "0.58"),
                _leg(113, 2, 275, "Chua, Jie Zhi Shane", 12, "M", False, "0.24"),
                _leg(114, 3, 633, "Taguchi, Maxwell Shouki", 4, "M", False, "0.57"),
            ), 114, "725d176bd84d5aa2623d8c071a8021fb7a545a11c35ec614768213f0ba1dd964",
        ),
        _target(
            30, _JUNIOR_DAY_1, "117", "Mixed 11-12 200 LC Meter Medley Relay",
            "Aquatic Performance Swim Club", "A", "2:16.96",
            (
                _leg(115, 1, 277, "Ler, Darian", 12, "M", False, "0.67"),
                _leg(116, 2, 394, "Edwards, Rebecca rae", 13, "W", False, "0.44"),
                _leg(117, 1, 118, "Cheong, Rae Min Kristen", 4, "W", False, "0.19"),
            ), 117, "48416581402aab863b646ff71391e6cb298b3bb7ec642dfd8e059485b49d5d96",
        ),
        _target(
            50, _JUNIOR_DAY_1, "117", "Mixed 11-12 200 LC Meter Medley Relay",
            "Aquatic Performance Swim Club", "B", "2:22.36",
            (
                _leg(192, 1, 221, "Nagamochi, Renji", 11, "M", True, "0.63"),
                _leg(193, 2, 694, "Verwijmeren, Luuk Pieter3 M)", 1, None, False, "0.46"),
                _leg(194, 4, 113, "Shang, Zu Yi Sierra Eve", 12, "W", False, None),
            ), 193, "33a454beb8710c2791ccc7625d3c5ced528d6bd2862b35b28faa24e1206eb079",
        ),
        _target(
            55, _JUNIOR_DAY_1, "117", "Mixed 11-12 200 LC Meter Medley Relay",
            "X Lab", "C", "2:55.95",
            (
                _leg(211, 1, 697, "Ee, Emma", 12, "W", False, "0.75"),
                _leg(212, 2, 698, "Abdul Khair, Daria Suhayr3 W) r1:02.53 Mark, Ivan Royston", 11, "M", False, "0.35"),
                _leg(213, 4, 651, "Lim, Le Jin", 12, "M", False, "0.27"),
            ), 212, "d1fc735a4301155cbf8f5da861f37e622d88630de565d203cb34862484300be1",
        ),
        _target(
            106, _JUNIOR_DAY_2, "317", "Boys 11-12 200 LC Meter Freestyle Relay",
            "Stamford American Internationa-ZZ", "A", "2:09.95",
            (
                _leg(414, 1, 581, "Yang, Lion", 11, None, True, "0.79"),
                _leg(415, 2, 797, "Davidovich Weisberg, Me3r)o rn:", 1, None, True, "0.09"),
                _leg(416, 4, 263, "Yu, Jun Heng Nathaniel", 12, None, True, "0.18"),
            ), 415, "ab87cefffbfd91b1529414ee9373c6ddff6f78a2dd73cf2246f01fd9c60edef8",
        ),
        _target(
            113, _JUNIOR_DAY_2, "317", "Boys 11-12 200 LC Meter Freestyle Relay",
            "Aquatic Performance Swim Club", "B", "2:07.09",
            (
                _leg(441, 1, 221, "Nagamochi, Renji", 11, None, True, "0.46"),
                _leg(442, 2, 798, "Verwijmeren, Luuk Pieter3", 1, None, False, "0.49"),
                _leg(443, 4, 235, "Jung, Albert", 11, None, True, "0.22"),
            ), 442, "6680a9807ac2cdfbb5150b35b2ba1587c115ba18413a4b77f34b5741a6b39c7e",
        ),
        _target(
            122, _JUNIOR_DAY_2, "318", "Girls 11-12 200 LC Meter Freestyle Relay",
            "Jaq (Ina)", "A", "2:06.47",
            (
                _leg(476, 1, 799, "Ratuwalangon, Ashima Adriana2 L) r1:20.42 *Tandhiwira, Airien", 12, None, True, "0.70"),
                _leg(477, 3, 58, "Winata, Brielle Elicia", 10, None, True, None),
                _leg(478, 4, 112, "Pattipeiluhu, Cinta Violend", 12, None, True, "0.23"),
            ), 476, "ef52a9000088388b2cc43435d36c854a34989f5ad97652ff40d804150180e817",
        ),
        _target(
            180, _JUNIOR_DAY_3, "519", "Girls 11-12 200 LC Meter Medley Relay",
            "Jaq (Ina)", "A", "2:21.01",
            (
                _leg(706, 1, 112, "Pattipeiluhu, Cinta Violend", 12, None, True, "0.66"),
                _leg(707, 2, 58, "Winata, Brielle Elicia", 10, None, True, None),
                _leg(708, 3, 836, "Ratuwalangon, Ashima A4d)r *iaTnaan d1h2iwira, Airien", 12, None, True, "0.43"),
            ), 708, "5ea19b23797dee6d3121adf625571f112a86ba1933f56b64cf1d750b260d5ef3",
        ),
        _target(
            211, _JUNIOR_DAY_3, "520", "Boys 11-12 200 LC Meter Medley Relay",
            "Aquatic Performance Swim Club", "A", "2:18.92",
            (
                _leg(829, 1, 230, "Foo, Isaac", 11, None, False, "0.52"),
                _leg(830, 2, 798, "Verwijmeren, Luuk Pieter3", 1, None, False, "0.21"),
                _leg(831, 4, 273, "Tay, Rui Jun Cleon", 12, None, False, "0.37"),
            ), 830, "7aaef09e3a744d19285f0dde9f32fefe4630fe8c5e1713bd1886e634ef24f2dd",
        ),
        _target(
            225, _SENIOR_DAY_1, "107", "Women 13 & Over 400 LC Meter Freestyle Relay",
            "Cis Huskies Swim Team-ZZ", "A", "4:32.94",
            (
                _leg(884, 1, 1519, "Vinayak, Leia", 16, None, True, "0.71"),
                _leg(885, 2, 1520, "du Bois de Vroylande, Ale3x)i ra:", 1, None, True, "0.41"),
                _leg(886, 4, 1521, "Hicks, Olivia", 18, None, True, "0.30"),
            ), 885, "f5f3a0ea4121f01898d15560b9a0ada76977e5280d3f0c3351decc5e82a1ad8f",
        ),
        _target(
            238, _SENIOR_DAY_2, "207", "Men 13 & Over 800 LC Meter Freestyle Relay",
            "Aquatic Performance Swim Club", "A", "8:17.84",
            (
                _leg(935, 1, 1136, "Chew, Jeryl", 16, None, False, "0.68"),
                _leg(936, 2, 1797, "Chong, Cher Loong Ayden3", 1, None, False, "0.45"),
                _leg(937, 4, 840, "Lee, Dylan Jian Hong", 14, None, False, "0.17"),
            ), 936, "a44c51847ca6a05a4cab16d40cb2a899a200cebf55b0712f8739eab012611290",
        ),
        _target(
            243, _SENIOR_DAY_2, "207", "Men 13 & Over 800 LC Meter Freestyle Relay",
            "Xavier School Swim Club", "A", "9:45.14",
            (
                _leg(954, 1, 1232, "Cortes, Frank Sebastian", 17, None, True, "0.72"),
                _leg(955, 2, 1799, "Sison, Brendan", 17, None, True, "0.34"),
                _leg(956, 3, 1800, "Ramirez, Santiago Emma4n)u *eSl i1a,8 Titus", 14, None, True, "0.40"),
            ), 956, "f66eacba3c4ed18bba12c8a95c68d6150079636114c684e0123c91d64ac9101e",
        ),
        _target(
            253, _SENIOR_DAY_3, "306", "Men 13 & Over 400 LC Meter Medley Relay",
            "SwimDolphia Aquatic School", "A", "4:20.35",
            (
                _leg(993, 1, 1463, "Tay, Cheng Kang, Joshua", 16, None, False, "0.57"),
                _leg(994, 2, 1670, "Lim, Yu Hao", 20, None, False, "0.36"),
                _leg(995, 3, 1849, "Low, Ka Hoang, Thaddeus4", 1, None, False, "0.69"),
            ), 995, "c4533e0ca310750dc4f9847a58e0a7b0c793b9f1f91c3bc24017654816a2497f",
        ),
        _target(
            272, _SENIOR_DAY_4, "407", "Mixed 13 & Over 400 LC Meter Medley Relay",
            "Aquatic Performance Swim Club", "A", "4:13.32",
            (
                _leg(1068, 1, 1136, "Chew, Jeryl", 16, "M", False, "0.55"),
                _leg(1069, 2, 915, "Lim, Gavin Louis", 16, "M", False, "0.25"),
                _leg(1070, 3, 1023, "Teo, Jing Wen Heather", 14, "W", False, "0.48"),
                _leg(1071, 7, 1511, "Wong, Ashley", 16, "W", False, "0.10"),
            ), 1071, "ddb13f18614fca4e84c5e3e86be4223c2d02a8e8242ceaa40696104d379a92cd",
        ),
        _target(
            277, _SENIOR_DAY_4, "407", "Mixed 13 & Over 400 LC Meter Medley Relay",
            "Cis Huskies Swim Team-ZZ", "A", "4:39.71",
            (
                _leg(1088, 1, 1477, "Kashyap, Shreyash J", 18, "M", True, "0.75"),
                _leg(1089, 2, 1194, "Bao, Haoyang", 16, "M", True, "0.22"),
                _leg(1090, 3, 1876, "du Bois de Vroylande, Ale4x)i *aV Win1a7yak, Leia", 16, "W", True, "0.34"),
            ), 1090, "1a0796d3d64c823e0799081c66475847e516661d1393e677781c168d149290ca",
        ),
        _target(
            279, _SENIOR_DAY_4, "407", "Mixed 13 & Over 400 LC Meter Medley Relay",
            "Effiswim Swim School", "A", "4:44.01",
            (
                _leg(1095, 1, 857, "Lee, Kai William", 14, "M", False, "0.61"),
                _leg(1096, 2, 1012, "Nguyen, Tram Anh Ngoc", 3, None, True, "0.17"),
                _leg(1097, 4, 1633, "Tran, Nathan Quoc Khanh", 14, "M", True, "0.24"),
            ), 1096, "826ad2a1f0eae697be9d261cc1eed2be020a4970c06fc9c499655fb48671c3e8",
        ),
        _target(
            283, _SENIOR_DAY_4, "407", "Mixed 13 & Over 400 LC Meter Medley Relay",
            "Thiha Swim Club (Myr)", "A", "5:07.55",
            (
                _leg(1110, 1, 1550, "Khant, Chan Naing", 17, "M", True, "0.75"),
                _leg(1111, 2, 1310, "Thar, Ngwe Chi Poe", 14, "W", True, "0.61"),
                _leg(1112, 3, 1618, "Htoon, Thoon Yamon", 14, "W", True, "0.60"),
                _leg(1113, 7, 1209, "Myo, Aung Myat", 16, "M", True, "0.14"),
            ), 1113, "e14d61c24b6db6804d28dd21b4bc1dac936d24026d354078ca1bdb7f1c622a08",
        ),
        _target(
            311, _SENIOR_DAY_5, "507", "Men 13 & Over 400 LC Meter Freestyle Relay",
            "Aquatic Performance Swim Club", "B", "3:46.34",
            (
                _leg(1222, 1, 1246, "See, Kai En Keagan", 15, None, False, "0.54"),
                _leg(1223, 2, 1797, "Chong, Cher Loong Ayden3", 1, None, False, "0.38"),
                _leg(1224, 4, 1167, "Keng, Kayden Xi Ze", 17, None, False, "0.27"),
            ), 1223, "18e05f1846fdf687a2650d594ca064098737814fea87755ac7b2f1bf3217d3ef",
        ),
        _target(
            344, _SENIOR_DAY_6, "606", "Women 13 & Over 400 LC Meter Medley Relay",
            "Singapore Swimming Club", "B", "4:49.81",
            (
                _leg(1348, 1, 1513, "Lim, Tien", 16, None, False, "0.66"),
                _leg(1349, 2, 1737, "Chin, Shin Ying Charisse", 13, None, False, "0.28"),
                _leg(1350, 5, 1487, "Sim, En Xi Sarah", 15, None, False, "0.30"),
                _leg(1351, 4, 1733, "Lee, Si Hui, Sophie", 16, None, False, "0.30"),
            ), 1350, "3cceaa8534512ab93335bd9410fcff771de87a7add85f17b61e3b60ae6a7edbc",
        ),
    ),
)
