import os
import logging
from pygly2.algorithms import database
from .common_transforms import (monoisotopic_mass,
                                reduced_mass,
                                permethelylated_mass,
                                derivatized_mass,
                                deuteroreduced_permethylated_mass)

from pygly2.utils import identity

logger = logging.getLogger(__name__)

default_fragmentation_parameters = {
    "kind": "ABCYXZ",
    "max_cleavages": 1,
    "average": False,
    "charge": 0
}


def mass_transform(record, derivatize_fn=identity, adduct_mass=0, adduct_number=0):
    derivatize_fn(record)
    mass = record.mass() + adduct_number * adduct_mass
    return mass


def extract_fragments(record, fragmentation_parameters=None):
    fragmentation_parameters = fragmentation_parameters or default_fragmentation_parameters
    return list(record.structure.fragments(**fragmentation_parameters))


def record_handle(record, mass_transform_parameters, fragmentation_parameters):
    mass = mass_transform(record, **(mass_transform_parameters or {}))
    fragments = extract_fragments(record, fragmentation_parameters)
    record.fragments = fragments
    record.intact_mass = mass
    return record


def prepare_database(in_database, out_database=None, mass_transform_parameters=None, fragmentation_parameters=None):
    if isinstance(in_database, str):
        in_database = database.RecordDatabase(in_database)
    if out_database is None:
        out_database_string = os.path.splitext(in_database.connection_string)[0] + ".out.db"
        out_database = database.RecordDatabase(out_database_string, record_type=in_database.record_type)
    elif isinstance(out_database, str):
        out_database = database.RecordDatabase(out_database, record_type=in_database.record_type)
    for i, record in enumerate(in_database):
        mass = mass_transform(record, **(mass_transform_parameters or {}))
        fragments = extract_fragments(record, fragmentation_parameters)
        record.fragments = fragments
        record.intact_mass = mass
        out_database.load_data([record], commit=False, mass_params={"override": mass})
        if i % 1 == 0:
            logger.info("%d records processed", i)
    out_database.commit()
    return out_database
