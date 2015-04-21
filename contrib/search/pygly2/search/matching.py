from math import fabs
from itertools import chain
from collections import defaultdict
from pygly2.utils import make_struct
from pygly2 import Composition

PROTON = Composition("H+").mass
DEFAULT_MS2_MATCH_TOLERANCE = 2e-5
DEFAULT_MS1_MATCH_TOLERANCE = 1e-5
FragmentMatch = make_struct("FragmentMatch", ["match_key", "mass", "ppm_error",
                                              "intensity", "charge", "scan_id"])
MergedMatch = make_struct("MergedMatch", ["match_key", "mass", "ppm_error", "intensity",
                                          "charge", "scan_id", "matches"])


def neutral_mass(mz, z):
    return (mz * z) - (z * PROTON)


def mass_charge_ratio(neutral_mass, z):
    return (neutral_mass + (z * PROTON)) / z

default_fragmentation_parameters = {
    "kind": "BYX",
    "max_cleavages": 2,
    "average": False,
    "charge": 0
}


def ppm_error(x, y):
    return (x - y) / y


def collect_similar_ions(fragments, tolerance=2e-8, redundant=True):
    '''
    Find clusters of close mass fragments.
    '''
    groups = defaultdict(list)
    membership = dict()
    for index in fragments:
        for other in fragments:
            if other.name in membership and not redundant:
                continue
            if fabs(ppm_error(index.mass, other.mass)) < tolerance:
                groups[index.name].append(other)
                membership[other.name] = index.name
    return groups


def find_matches(precursor, msms_db, ms1_match_tolerance=DEFAULT_MS1_MATCH_TOLERANCE,
                 ms2_match_tolerance=DEFAULT_MS2_MATCH_TOLERANCE, ion_types="ABCXYZ"):
    '''
    Find all MS1 matches, find all MS2 matches in these matches, and merge the fragments found.
    '''
    results = []
    precursor_ppm_errors = []
    scans_searched = set()
    i = 0

    precursor.fragments = [f for f in precursor.fragments if f.kind[-1] in ion_types]

    for row in msms_db.ppm_match_tolerance_search(precursor.intact_mass, ms1_match_tolerance):
        row = msms_db.precursor_type.from_sql(row, msms_db)
        precursor_ppm_errors.append(ppm_error(precursor.mass(), row.neutral_mass))
        scans_searched.update(row.scan_ids)
        matches = match_fragments(precursor.fragments, row.tandem_data)
        results.append(matches)
        i += 1
    precursor.ppm_error = precursor_ppm_errors
    precursor.scan_ids = scans_searched
    precursor.intact_structures_searched = i
    precursor.matches = collect_matches(chain.from_iterable(results))
    return precursor


def match_fragments(fragments, peak_list, ms2_match_tolerance=DEFAULT_MS2_MATCH_TOLERANCE):
    '''
    Match theoretical MS2 fragments against the observed peaks.
    '''
    matches = []
    for fragment in fragments:
        for peak in peak_list:
            match_error = fabs(ppm_error(fragment.mass, peak.mass))
            if match_error <= ms2_match_tolerance:
                matches.append(FragmentMatch(
                    fragment.name, peak.mass, match_error, peak.intensity, peak.charge, peak.id))
    return matches


def collect_matches(matches):
    '''
    Groups matches to the same theoretical ions into lists, and calls :func:`merge_matches`
    on each group
    '''
    acc = defaultdict(list)
    for match in matches:
        acc[match.match_key].append(match)
    return map(merge_matches, acc.values())


def merge_matches(matches):
    '''
    Merge a list of :class:`FragmentMatch` instances into a single :class:`MergedMatch`
    '''
    best_ppm = float('inf')
    best_match = None
    match_map = {}
    for match in matches:
        if fabs(match.ppm_error) < fabs(best_ppm):
            best_ppm = match.ppm_error
            best_match = match
        match_map[match.scan_id] = match
    merged = MergedMatch(best_match.match_key, best_match.mass, best_match.ppm_error,
                         best_match.intensity, best_match.charge,
                         best_match.scan_id, match_map)
    return merged
