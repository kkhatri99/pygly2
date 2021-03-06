from pygly2.composition import Composition
from collections import defaultdict
import warnings

do_warn = True


class CompositionRule(object):
    def __init__(self, base_composition, position_shifts=None):
        if position_shifts is None:
            position_shifts = {}
        self.composition = Composition(base_composition)
        self.position_shifts = defaultdict(Composition)
        self.position_shifts.update(position_shifts)

    def __call__(self, position=-1):
        # Implicitly copies
        return (self.composition + Composition(self.position_shifts[position]))


class CompositionIndex(dict):

    def __getitem__(self, key):
        try:
            composition_dict = super(CompositionIndex, self).__getitem__(key)
        except KeyError:
            composition_dict = Composition()
            if do_warn:
                warnings.warn("{key} could not be found. It may not have an explicit composition".format(key=key),
                              stacklevel=3)
        # Explicitly copies
        return (composition_dict).clone()


class CompositionRuleIndex(dict):

    def __getitem__(self, key):
        try:
            rule = super(CompositionRuleIndex, self).__getitem__(key)
        except KeyError:
            rule = CompositionRule()
            if do_warn:
                warnings.warn("{key} could not be found. It may not have an explicit composition".format(key=key),
                              stacklevel=3)
        return (rule)


# Monosaccharide Residue Compositions
_monosaccharide_compositions = {
    "sug": Composition({
        "C": 2,
        "H": 4,
        "O": 2
    }),
    "tri": Composition({
        "C": 3,
        "H": 6,
        "O": 3
    }),
    "tet": Composition({
        "C": 4,
        "H": 8,
        "O": 4
    }),
    "pen": Composition({
        "C": 5,
        "H": 10,
        "O": 5
    }),
    "hex": Composition({
        "C": 6,
        "H": 12,
        "O": 6
    }),
    "hep": Composition({
        "C": 7,
        "H": 14,
        "O": 7
    }),
    "oct": Composition({
        "C": 8,
        "H": 16,
        "O": 8
    }),
    "non": Composition({
        "C": 9,
        "H": 18,
        "O": 9
    }),
    "dec": Composition({
        "C": 10,
        "H": 20,
        "O": 10
    }),
    "s11": Composition("H2CO") * 11,
    "s12": Composition("H2CO") * 12,
    "s13": Composition("H2CO") * 13,
    "s14": Composition("H2CO") * 14,
    "s15": Composition("H2CO") * 15,
    "s16": Composition("H2CO") * 16,
    "s17": Composition("H2CO") * 17,
    "s18": Composition("H2CO") * 18,
    "s19": Composition("H2CO") * 19,
    "s20": Composition("H2CO") * 20
}

monosaccharide_composition = CompositionIndex(_monosaccharide_compositions)

#: Modification Compositions defined as dictionaries, specified as composition
#: deltas relative to the glycan structure
_modification_compositions = {
    "d": CompositionRule({
        "O": -1,
    }),
    "a": CompositionRule({
        "H": -2,
        "O": 1
    }, {1: {"H": 2}}),
    "keto": CompositionRule({"H": -2}),
}

modification_compositions = CompositionRuleIndex(_modification_compositions)

# Specified as composition deltas relative to the glycan structure
_substituent_compositions = {
    "n_acetyl": Composition({
        "C": 2,
        "H": 5,
        "N": 1,
        "O": 1,
    }),
    "sulfate": Composition({
        "S": 1,
        "O": 3,
        "H": 2
    }),
    "amino": Composition({
        "N": 1,
        "H": 3,
    }),
    "n_glycolyl": Composition({
        "C": 2,
        "H": 5,
        "O": 2,
        "N": 1
    }),
    "phosphate": Composition({
        'P': 1,
        'O': 3,
        'H': 3
    }),
    "acetyl": Composition({
        'H': 4,
        'C': 2,
        'O': 1
    }),
    "methyl": Composition({
        'H': 4,
        'C': 1
    }),
    "n_sulfate": Composition({
        "H": 3,
        'S': 1,
        'O': 3,
        'N': 1
    }),
    "nitrate": Composition({
        "N": 1,
        "O": 3
    }),
    "iodo": Composition({
        "I": 1,
        "H": 1,
    }),
    "flouro": Composition("FH"),
    "imino": Composition("NH2"),
    "chloro": Composition("ClH"),
    "formyl": Composition("CHOH"),
    "bromo": Composition("BrH"),
    "pyruvate": Composition("COCOCH3H"),
    "n_alanine": Composition({
      "C": 3,
      "H": 8,
      "N": 2,
      "O": 1
    }),
    "n_dimethyl": Composition("N(CH3)2H"),
    "n_formyl": Composition("NHCHOH"),
    "n_methyl": Composition("NHCH3H"),
    "n_succinate": Composition("NCOCH2CH2COOHH"),
    "n_trifluoroacetyl": Composition("NHCOCF3H"),
    "thio": Composition("SHH")
}

substituent_compositions = CompositionIndex(_substituent_compositions)
