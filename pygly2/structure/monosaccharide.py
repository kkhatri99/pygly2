import logging
from uuid import uuid4
from itertools import chain, izip_longest

from .constants import Anomer, Configuration, Stem, SuperClass, Modification, RingType
from .substituent import Substituent
from .link import Link
from .base import SaccharideBase

from ..io.format_constants_map import anomer_map, superclass_map
from ..utils import invert_dict, make_counter, StringIO, identity as ident_op
from ..utils.multimap import OrderedMultiMap
from ..utils.enum import EnumValue
from ..composition import Composition, calculate_mass
from ..composition.structure_composition import monosaccharide_composition
from ..composition.structure_composition import modification_compositions

anomer_map = invert_dict(anomer_map)
superclass_map = invert_dict(superclass_map)

logger = logging.getLogger(__name__)
logger.setLevel("DEBUG")

debug = True


def _get_standard_composition(monosaccharide):
    '''Used to get initial composition for a given monosaccharide
    |Superclass| and modifications.

    Used during initialization of a |Monosaccharide|.

    Parameters
    ----------
    monosaccharide: :class:`Monosaccharide`
        The |Monosaccharide| object to read attributes from

    Returns
    -------
    :class:`~pygly2.composition.composition.Composition`:
        The baseline composition from `monosaccharide.superclass` + `monosaccharide.modifications`
    '''
    base = monosaccharide_composition[monosaccharide.superclass]
    modifications = list(monosaccharide.modifications.items())
    for mod_pos, mod_val in modifications:
        # Don't set the reducing end here
        if isinstance(mod_val, ReducedEnd):
            monosaccharide.reducing_end = mod_val
            continue
        elif mod_val is Modification.aldi:
            monosaccharide.reducing_end = True
            continue
        try:
            base += modification_compositions[mod_val](mod_pos)
        except:
            base += mod_val.composition
    return base


def traverse(monosaccharide, visited=None, apply_fn=ident_op):
    '''
    A low-level depth-first traversal method for unwrapped residue
    graphs

    Parameters
    ----------
    monosaccharide: :class:`Monosaccharide`
        Residue to start traversing from
    visited: set or None
        The collection of node ids to ignore, having already visited them. If |None|, it defaults
        to the empty set.
    apply_fn: function
        Function to apply to each residue before yielding them

    Yields
    -------
    :class:`Monosaccharide`
    '''
    if visited is None:
        visited = set()
    yield apply_fn(monosaccharide)
    visited.add(monosaccharide.id)
    outnodes = sorted(list(monosaccharide.links.items()), key=lambda x: x[1][monosaccharide].order(), reverse=True)
    for p, link in outnodes:
        child = link[monosaccharide]
        if child.id in visited:
            continue
        for grandchild in traverse(child, visited=visited, apply_fn=apply_fn):
            yield grandchild


def graph_clone(monosaccharide, visited=None):
    '''
    Low-level depth-first duplication method for unwrapped residue graphs

    Parameters
    ----------
    residue: :class:`Monosaccharide`
        The root of the graph to clone
    visited: set or None
        The collection of node ids to ignore, having already visited them. If |None|, it defaults
        to the empty set.

    Returns
    -------
    :class:`Monosaccharide`:
        The root of a newly duplicated and identical residue graph
    '''
    clone_root = monosaccharide.clone(prop_id=True)
    node_stack = [(clone_root, monosaccharide)]
    visited = set() if visited is None else visited
    while(len(node_stack) > 0):
        clone, ref = node_stack.pop()
        if ref.id in visited:
            continue
        visited.add(ref.id)
        links = [link for pos, link in ref.links.items()]
        for link in links:
            terminal = link.to(ref)
            if terminal.id in visited:
                continue
            clone_terminal = terminal.clone(prop_id=True)
            clone_terminal.id = terminal.id
            if link.is_child(terminal):
                link.clone(clone, clone_terminal)
            else:
                link.clone(clone_terminal, clone)

            node_stack.append((clone_terminal, terminal))
    return clone_root


def release(monosaccharide):
    '''
    Break all monosaccharide-monosaccharide links on `monosaccharide`, returning
    them as a list. Breaking is done with `refund=True`
    '''
    return [(link, link.try_break_link(refund=True)) for link in list(monosaccharide.links.values())]


def toggle(monosaccharide):
    '''
    A simple generator for declaratively masking and masking a residue's links. The
    first iteration masks all links. The second unmasks them. Calls :func:`release`
    '''
    links = release(monosaccharide)
    yield links
    [link.try_apply() for link, termini in links]
    yield False


class Monosaccharide(SaccharideBase):

    '''
    Represents a single monosaccharide molecule, and its relationships with other
    molcules through |Link| objects. |Link| objects stored in :attr:`links` for connections to other
    |Monosaccharide| instances, building a |Glycan|
    structure as a graph of |Monosaccharide| objects. |Link|
    objects connecting the |Monosaccharide| instance to |Substituent|
    objects are stored in :attr:`substituent_links`.

    Both :attr:`links` and :attr:`substituent_links` are instances of
    |OrderedMultiMap| objects where the key is the index of the
    carbon atom in the carbohydrate backbone that hosts the bond.
    An index of `x` or `-1` represents an unknown location.

    Attributes
    ----------
    anomer: :class:`Anomer` or {'alpha', 'beta', 'uncyclized', 'x', 'missing', None}
        An entry of :class:`~pygly2.structure.constants.Anomer` that corresponds to the linkage type
        of the carbohydrate backbone. Is an entry of a class based on :class:`Enum`
    superclass: :class:`SuperClass` or {'tri', 'tet', 'pen', 'hex', 'hep', 'oct', 'non' 'missing', 'x', None}
        An entry of :class:`~pygly2.structure.constants.SuperClass` that corresponds to the number of
        carbons in the carbohydrate backbone of the monosaccharide. Controls the base composition of the
        instance and the number of positions open to be linked to or modified. Is an entry of a class
        based on :class:`Enum`
    configuration: :class:`Configuration` or {'d', 'l', 'x', 'missing', None}
        An entry of |Configuration| which corresponds to the optical
        stereomer state of the instance. Is an entry of a class based on :class:`Enum`. May possess
        more than one value.
    stem: :class:`Stem` or {"gro", "ery", "rib", "ara", "all", "alt", "glc", "man", "tre", "xyl", "lyx", "gul", "ido", "gal", "tal", "thr", 'x', 'missing', None}
        Corresponds to the bond conformation of the carbohydrate backbone. Is an entry of a class based
        on :class:`Enum`. May possess more than one value.
    ring_start: int or {0, -1, 'x', None}
        The index of the carbon of the carbohydrate backbone that starts a ring. A value of `-1`, `'x'`, or
        |None| corresponds to an unknown start. A value of `0` refers to a linear chain.
    ring_end:  int or {0, -1, 'x', None}
        The index of the carbon of the carbohydrate backbone that ends a ring. A value of `-1`, `'x'`, or
        |None| corresponds to an unknown ends. A value of `0` refers to a linear chain.
    reducing_end: :class:`int`
        The index of the carbon which hosts the reducing end.
    modifications: |OrderedMultiMap|
        The mapping of sites to |Modification| entries. Directly modifies the instance's :attr:`composition`
    links: |OrderedMultiMap|
        The mapping of sites to |Link| entries that refer to other |Monosaccharide| instances
    substituent_links: |OrderedMultiMap|
        The mapping of sites to |Link| entries that refer to
        |Substituent| instances.
    composition: |Composition|
        An instance of |Composition| corresponding to the elemental composition
        of ``self`` and its immediate modifications. If not provided, this will be inferred
        from field values.
    reduced: ReducedEnd
        An instance of ReducedEnd, or the value |True|, represents a reduced sugar. May be inferred
        from `modifications` if "aldi" is present
    '''

    def __init__(self, anomer=None, configuration=None, stem=None,
                 superclass=None, ring_start=None, ring_end=None,
                 modifications=None, links=None, substituent_links=None,
                 composition=None, reduced=None, id=None, fast=False):

        if modifications is None:
            modifications = OrderedMultiMap()

        if fast:
            self._anomer = anomer
            self._configuration = tuple(configuration)
            self._stem = tuple(stem)
            self._superclass = superclass
        else:
            self.anomer = anomer
            self.configuration = configuration
            self.stem = stem
            self.superclass = superclass

        self.ring_start = ring_start
        self.ring_end = ring_end
        self.modifications = modifications
        self.links = OrderedMultiMap() if links is None else links
        self.substituent_links = OrderedMultiMap() if substituent_links\
            is None else substituent_links
        self.id = id or uuid4().int
        self._reducing_end = None
        self.reducing_end = reduced
        if composition is None:
            composition = _get_standard_composition(self)
        self.composition = composition

    @property
    def anomer(self):
        return self._anomer

    @anomer.setter
    def anomer(self, value):
        self._anomer = Anomer[value]

    @property
    def configuration(self):
        return self._configuration

    @configuration.setter
    def configuration(self, value):
        if isinstance(value, (tuple, list)):
            self._configuration = tuple(Configuration[v] for v in value)
        else:
            self._configuration = (Configuration[value],)

    @property
    def stem(self):
        return self._stem

    @stem.setter
    def stem(self, value):
        if isinstance(value, (tuple, list)):
            self._stem = tuple(Stem[v] for v in value)
        else:
            self._stem = (Stem[value],)

    @property
    def superclass(self):
        return self._superclass

    @superclass.setter
    def superclass(self, value):
        self._superclass = SuperClass[value]

    def clone(self, prop_id=False, fast=True):
        '''
        Copies just this |Monosaccharide| and its |Substituent|s, creating a separate instance
        with the same data. All mutable data structures are duplicated and distinct from the original.

        Does not copy any :attr:`links` as this would cause recursive duplication of the entire |Glycan|
        graph.

        Returns
        -------
        :class:`Monosaccharide`

        '''
        modifications = OrderedMultiMap()
        for k, v in self.modifications.items():
            if isinstance(v, ReducedEnd):
                continue
            modifications[k] = Modification[v]

        monosaccharide = Monosaccharide(
            superclass=self.superclass,
            stem=self.stem,
            configuration=self.configuration,
            ring_start=self.ring_start,
            ring_end=self.ring_end,
            modifications=modifications,
            anomer=self.anomer,
            reduced=self.reducing_end.clone() if self.reducing_end is not None else None,
            id=self.id if prop_id else None,
            fast=fast)
        for pos, link in self.substituent_links.items():
            sub = link.to(self)
            dup = sub.clone()
            Link(monosaccharide, dup, link.parent_position, link.child_position,
                 link.parent_loss, link.child_loss)

        return monosaccharide

    @property
    def ring_type(self):
        """The size of the ring-shape of the carbohydrate, as computed
        by ring_end - ring_start.

        Returns
        -------
        :class:`EnumValue`:
            The appropriate value of :class:`.RingType`
        """

        try:
            diff = self.ring_end - self.ring_start
            if diff == 4:
                return RingType.pyranose
            elif diff == 3:
                return RingType.furanose
            elif diff == 0:
                return RingType.open
        except TypeError:
            pass
        return RingType.x

    @property
    def reducing_end(self):
        """Return the reducing end type of
        `self` or |None| if `self` is not reduced. The reducing end value
        can also be found in :attr:`modifications`.

        If `Modification.aldi` is present, it will be converted into
        an instance of :class:`.ReducedEnd` with default arguments.

        Returns
        -------
        :class:`.ReducedEnd` or |None|
        """
        if self._reducing_end is None:
            for pos, mod in list(self.modifications.items()):
                if isinstance(mod, ReducedEnd):
                    self._reducing_end = mod
                    break
                elif mod is Modification.aldi:  # pragma: no cover
                    self.modifications.popv(Modification.aldi)
                    self.reducing_end = ReducedEnd()
                    break
        return self._reducing_end

    @reducing_end.setter
    def reducing_end(self, value):
        """Sets the reducing end type of `self`.

        If `value` is |None|, then this residue is not reduced.
        Else, if `value` ``is True``, then this residue's reducing end
        is set to an instance of :class:`.ReducedEnd` with default parameters.
        Else, this residue's reducing_end is set to `value`.

        This process will scan :attr:`modifications` for a pre-existing `reducing_end`
        value to replace.

        Parameters
        ----------
        value: True, None, or :class:`.ReducedEnd`

        """
        red_end = self.reducing_end
        if red_end is not None:
            self.modifications.pop(1, red_end)
        # Setting to None will un-reduce the sugar, but should not
        # put a None in :attr:`modifications`
        if value:
            if value is True:
                value = ReducedEnd()
            self.modifications[1] = value
            self._reducing_end = value
        else:
            self._reducing_end = value

    def __getitem__(self, position):
        '''
        Gets the collection of alterations made to the carbohydrate
        backbone at `position`. This queries :attr:`modifications`, :attr:`links`, and
        :attr:`substituent_links`.

        Returns
        -------
        :class:`dict`
        '''
        return {
            'modifications': self.modifications[position],
            'substituent_links': self.substituent_links[position],
            'links': self.links[position]
            }

    def open_attachment_sites(self, max_occupancy=0):
        '''
        When attaching :class:`Monosaccharide` instances to other objects,
        bonds are formed between the carbohydrate backbone and the other object.
        If a site is already bound, the occupying object fills that space on the
        backbone and prevents other objects from binding there.

        Currently only cares about the availability of the hydroxyl group. As there
        is not a hydroxyl attached to the ring-ending carbon, that should not be
        considered an open site.

        If any existing attached units have unknown positions, we can't provide any
        known positions, in which case the list of open positions will be a :class:`list`
        of ``-1`` s of the length of open sites.

        Parameters
        ----------
        max_occupancy: :class:`int`
            The number of objects that may already be bound at a site before it
            is considered unavailable for attachment.

        Returns
        -------
        :class:`list`:
            The positions open for binding
        :class:`int`:
            The number of bound but unknown locations on the backbone.
        '''
        slots = [0] * self.superclass.value
        unknowns = 0
        for pos, obj in chain(self.modifications.items(),
                              self.links.items(),
                              self.substituent_links.items()):
            if obj == Modification.keto:
                continue
            if pos in {-1, 'x'}:
                unknowns += 1
            else:
                slots[pos - 1] += 1

        open_slots = []
        can_determine_positions = unknowns > 0 or (self.ring_end in {-1, 'x'})

        for i in range(len(slots)):
            if slots[i] <= max_occupancy and (i + 1) != self.ring_end:
                open_slots.append(
                    (i + 1) if not can_determine_positions else -1)

        if self.ring_end in {-1, 'x'}:
            open_slots.pop()

        return open_slots, unknowns

    def is_occupied(self, position):
        '''
        Checks to see if a particular backbone position is occupied by a :class:`~.constants.Modification`,
        :class:`~.substituent.Substituent`, or :class:`~.link.Link` to another :class:`Monosaccharide`.

        Parameters
        ----------
        position: int
            The position to check for occupancy. Passing -1 checks for undetermined attachments.

        Returns
        -------
        int:
            The number of occupants at ``position``

        Raises
        ------
        IndexError:
            When the position is less than 1 or exceeds the limits of the carbohydrate backbone's size.

        '''

        if (position > self.superclass.value) or (position < 1 and position not in {'x', -1, None}):
            raise IndexError("Index out of bounds")
        # The unknown position is always available
        if position in {-1, 'x'}:
            return 0
        n_occupants = len(self.links[position]) +\
            len(self.modifications[position]) +\
            len(self.substituent_links[position])
        if Modification.keto in self.modifications[position]:
            n_occupants -= 1
        return n_occupants

    def add_modification(self, modification, position, max_occupancy=0):
        '''
        Adds a modification instance to :attr:`modifications` at the site given
        by ``position``. This directly modifies :attr:`composition`, consequently
        changing :meth:`mass`

        Parameters
        ----------
        position: int or 'x'
            The location to add the :class:`~.constants.Modification` to.
        modification: str or Modification
            The modification to add. If passed a |str|, it will be
            translated into an instance of :class:`~pygly2.structure.constants.Modification`
        max_occupancy: int, optional
            The maximum number of items acceptable at `position`. defaults to :const:`1`

        Raises
        ------
        IndexError
            ``position`` exceeds the bounds set by :attr:`superclass`.
        ValueError
            ``position`` is occupied by more than ``max_occupancy`` elements

        Returns
        -------
        :class:`Monosaccharide`:
            `self`, for chain calls
        '''
        if self.is_occupied(position) > max_occupancy:
            raise ValueError("Site is already occupied")
        if modification is Modification.aldi:
            self.reducing_end = ReducedEnd()
        else:
            try:
                self.composition += modification_compositions[modification](position)
                self.modifications[position] = Modification[modification]
            except:
                self.composition += modification.composition
                self.modifications[position] = modification
        return self

    def drop_modification(self, position, modification):
        '''
        Remove the `modification` at `position`

        Parameters
        ----------
        position: int
            The position to drop the modification from
        modification: Modification
            The Modification to remove.

        Raises
        ------
        IndexError:
            If `position` is not a valid carbohydrate backbone position

        ValueError:
            If `modification` is not found at `position`

        Returns
        -------
        :class:`Monosaccharide`:
            `self`, for chain calls
        '''
        if position > self.superclass.value or position < 0 and position not in {'x', -1}:
            raise IndexError("Index out of bounds")
        try:
            self.modifications.pop(position, modification)
        except IndexError:
            raise ValueError("Modification {} not found at {}".format(modification, position))
        if modification is Modification.aldi:
            self.reducing_end = None
        else:
            try:
                self.composition = self.composition - \
                    modification_compositions[modification](position)
            except:
                self.composition = self.composition - modification.composition
        return self

    def add_substituent(self, substituent, position=-1, max_occupancy=0,
                        child_position=1, parent_loss=None, child_loss=None):
        '''
        Adds a :class:`~pygly2.structure.substituent.Substituent` and associated :class:`~pygly2.structure.link.Link`
        to :attr:`substituent_links` at the site given by ``position``. This new substituent is included when
        calculating mass with substituents included

        Parameters
        ----------
        substituent: str or Substituent
            The substituent to add. If passed a |str|, it will be
            translated into an instance of |Substituent|
        position: int or 'x'
            The location to add the |Substituent| link to :attr:`substituent_links`. Defaults to -1
        child_position: int
            The location to add the link to in `substituent`'s :attr:`links`. Defaults to -1. Substituent
            indices are currently not checked.
        max_occupancy: int, optional
            The maximum number of items acceptable at ``position``. Defaults to :const:`1`
        parent_loss: Composition or str
            The elemental composition removed from ``self``
        child_loss: Composition or str
            The elemental composition removed from ``substituent``

        Raises
        ------
        IndexError
            ``position`` exceeds the bounds set by :attr:`superclass`.
        ValueError
            ``position`` is occupied by more than ``max_occupancy`` elements


        Returns
        -------
        :class:`Monosaccharide`:
            `self`, for chain calls
        '''
        if self.is_occupied(position) > max_occupancy:
            raise ValueError("Site is already occupied")
        if child_loss is None:
            child_loss = Composition("H")
        if parent_loss is None:
            parent_loss = Composition("H")
        if isinstance(substituent, basestring):
            substituent = Substituent(substituent)
        Link(parent=self, child=substituent,
             parent_position=position, child_position=child_position,
             parent_loss=parent_loss, child_loss=child_loss)
        return self

    def drop_substituent(self, position, substituent=None, refund=True):
        '''
        Remove the `substituent` at `position`.

        If `substituent` is |None|, then the first substituent found at `position` is
        removed.

        Parameters
        ----------
        position: int
            The position to drop the modification from
        substituent: Substituent
            The |Substituent| to remove. If |None|, the first substituent found at
            `position` will be removed
        refund: bool
            Passed to :meth:`~.Link.break_link`

        Raises
        ------
        IndexError:
            If `position` is not a valid carbohydrate backbone position

        ValueError:
            If `substituent` is not found at `position`

        Returns
        -------
        :class:`Monosaccharide`:
            `self`, for chain calls
        '''
        if position > self.superclass.value or position < 0 and position not in {-1, 'x'}:
            raise IndexError("Index out of bounds")
        if isinstance(substituent, basestring):
            substituent = Substituent(substituent)
        link_obj = None
        for substituent_link in self.substituent_links[position]:
            if substituent is None or substituent_link.child.name == substituent.name:
                link_obj = substituent_link
                break
        if link_obj is None:
            if substituent is not None:
                msg = "No matching substituent found at {position}.".format(
                    position=position)
            else:
                msg = "No substituents found at {position}.".format(
                    position=position)
            raise IndexError(msg)

        link_obj.break_link(refund=refund)
        return self

    def add_monosaccharide(self, monosaccharide, position=-1, max_occupancy=0,
                           child_position=-1,
                           parent_loss=None, child_loss=None):
        '''
        Adds a |Monosaccharide| and associated |Link| to :attr:`links` at the site given by
        ``position``.

        Parameters
        ----------
        monosaccharide: Monosaccharide
            The monosaccharide to add.
        position: int or 'x'
            The location to add the |Monosaccharide| link to :attr:`links`. Defaults to -1
        child_position: int
            The location to add the link to in `monosaccharide`'s :attr:`links`. Defaults to -1.
        max_occupancy: int, optional
            The maximum number of items acceptable at ``position``. Defaults to :const:`1`
        parent_loss: Composition or str
            The elemental composition removed from ``self``
        child_loss: Composition or str
            The elemental composition removed from ``monosaccharide``

        Raises
        ------
        IndexError
            ``position`` exceeds the bounds set by :attr:`superclass`.
        ValueError
            ``position`` is occupied by more than ``max_occupancy`` elements


        Returns
        -------
        :class:`Monosaccharide`:
            `self`, for chain calls
        '''
        if parent_loss is None:
            parent_loss = Composition(H=1)
        if child_loss is None:
            child_loss = Composition(H=1, O=1)
        if self.is_occupied(position) > max_occupancy:
            raise ValueError("Parent Site is already occupied")
        if monosaccharide.is_occupied(child_position) > max_occupancy:
            raise ValueError("Child Site is already occupied")
        Link(parent=self, child=monosaccharide,
             parent_position=position, child_position=child_position,
             parent_loss=parent_loss, child_loss=child_loss)
        return self

    def drop_monosaccharide(self, position, refund=True):
        '''
        Remove the glycosidic bond at `position`, detatching a connected |Monosaccharide|

        If there is more than one glycosidic bond at `position`, an error will be raised.

        Parameters
        ----------
        position: int
            The position to drop the modification from
        refund: bool
            Passed to :meth:`~.Link.break_link`

        Raises
        ------
        IndexError:
            If `position` is not a valid carbohydrate backbone position

        ValueError:
            If no |Link| or more than one |Link| is found at `position`

        Returns
        -------
        :class:`Monosaccharide`:
            `self`, for chain calls
        '''
        if position > self.superclass.value or position < 0 and position not in {-1, 'x'}:
            raise IndexError("Index out of bounds")
        link_obj = None
        if len(self.links[position]) > 1:
            raise ValueError("Too many monosaccharides found")
        for link in self.links[position]:
            link_obj = link
            break
        if link_obj is None:
            raise ValueError(
                "No matching monosaccharide found at {position}".format(position=position))

        link_obj.break_link(refund=refund)
        return self

    def to_glycoct(self, res_index=None, lin_index=None, complete=True):
        '''
        If ``complete`` is True, returns the Monosaccharide instance formatted as condensed GlycoCT text.
        Otherwise, returns each line of the representation in a partitioned list:
        1. ``list`` of each line in the *RES* section, the monosaccharide residue itself,
        and each of its substituents
        2. ``list`` of each line in the *LIN* section connecting the monosaccharide to each substituent.
        Does *not* include links to other objects from `self.links` to avoid recursively building an
        entire glycan graph.
        3. ``int`` corresponding to the numerical index of the monosaccharide residue to be used to refer
        to it when building monosaccharide to monosaccharide *LIN* entries.

        ``complete = False`` is used by :meth:`~.glycan.Glycan.to_glycoct` to build the full graph in parts.

        Parameters
        ----------
        res_index : function, optional
            A function to yield index numbers for the *RES* section. If not provided, defaults to :func:`~pygly2.utils.make_counter`
        lin_index : function, optional
            A function to yield index numbers for the *LIN* section. If not provided, defaults to :func:`~pygly2.utils.make_counter`
        complete : bool, optional
            Format the object completely, returning a self-contained condensed GlycoCT string. Defaults to :const:`True`

        Returns
        -------
        :class:`str`
        '''
        residue_template = "{ix}b:{anomer}{conf_stem}{superclass}-{ring_start}:{ring_end}{modifications}"
        if res_index is None:
            res_index = make_counter()
        if lin_index is None:
            lin_index = make_counter()

        # This index is reused many times
        monosaccharide_index = res_index()

        # Format individual fields
        anomer = anomer_map[self.anomer]
        conf_stem = ''.join("-{0}{1}".format(c.name, s.name)
                            for c, s in zip(self.configuration, self.stem))
        superclass = "-" + superclass_map[self.superclass]

        modifications = '|'.join(
            "{0}:{1}".format(k, v.name) for k, v in self.modifications.items())

        modifications = "|" + modifications if modifications != "" else ""
        ring_start = self.ring_start if self.ring_start is not None else 'x'
        ring_end = self.ring_end if self.ring_end is not None else 'x'

        # The complete monosaccharide residue line
        residue_str = residue_template.format(ix=monosaccharide_index, anomer=anomer, conf_stem=conf_stem,
                                              superclass=superclass, modifications=modifications,
                                              ring_start=ring_start, ring_end=ring_end)
        res = [residue_str]
        lin = []
        # Construct the substituent lines
        # and their links
        for lin_pos, link_obj in self.substituent_links.items():
            sub = link_obj.to(self)
            sub_index = res_index()
            subst_str = str(sub_index) + sub.to_glycoct()
            res.append(subst_str)
            lin.append(
                link_obj.to_glycoct(lin_index(), monosaccharide_index, sub_index))

        # Completely render the data if `complete`
        if complete:
            buff = StringIO()
            buff.write("RES\n")
            buff.write('\n'.join(res))
            if len(lin) > 0:
                buff.write("\nLIN\n")
                buff.write("\n".join(lin))
            return buff.getvalue()
        else:
            return [res, lin, monosaccharide_index]

    def _flat_equality(self, other, lengths=True):
        '''
        Test for equality of all scalar-ish features that do not
        require recursively comparing links which in turn compare their
        connected units.
        '''
        flat = (self.anomer == other.anomer) and\
            (self.ring_start == other.ring_start) and\
            (self.ring_end == other.ring_end) and\
            (self.superclass == other.superclass) and\
            (self.modifications) == (other.modifications) and\
            (self.configuration) == (other.configuration) and\
            (self.stem) == (other.stem)
        if lengths:
            flat = flat and\
                len(self.links) == len(other.links) and\
                len(self.substituent_links) == len(other.substituent_links) and\
                self.total_composition() == other.total_composition()
        return flat

    def exact_ordering_equality(self, other, substituents=True):
        '''
        Performs equality testing between two monosaccharides where
        the exact position (and ordering by sort) of links must to match between
        the input |Monosaccharide| objects

        Returns
        -------
        |bool|
        '''
        if self._flat_equality(other):
            if substituents:
                for a_sub, b_sub in zip(self.substituents(), other.substituents()):
                    if a_sub != b_sub:
                        return False
            for a_mod, b_mod in zip(self.modifications.items(), other.modifications.items()):
                if a_mod != b_mod:
                    return False
            for a_child, b_child in zip(self.children(), other.children()):
                if a_child[0] != b_child[0]:
                    return False
                if not a_child[1].exact_ordering_equality(b_child[1], substituents=substituents):
                    return False
            return True
        return False

    def topological_equality(self, other, substituents=True):
        '''
        Performs equality testing between two monosaccharides where
        the exact ordering of child links does not have to match between
        the input |Monosaccharide|s, so long as an exact match of the
        subtrees is found

        Returns
        -------
        |bool|
        '''
        if self._flat_equality(other) and (not substituents or self._match_substituents(other)):
            taken_b = set()
            b_children = list(other.children())
            a_children = list(self.children())
            for a_pos, a_child in a_children:
                matched = False
                for b_pos, b_child in b_children:
                    if (b_pos, b_child.id) in taken_b:
                        continue
                    if a_child.topological_equality(b_child, substituents=substituents):
                        matched = True
                        taken_b.add((b_pos, b_child.id))
                        break
                if not matched and len(a_children) > 0:
                    return False
            if len(taken_b) != len(b_children):
                return False
            return True
        return False

    def _match_substituents(self, other):
        '''
        Helper method for matching substituents in an order-independent
        fashion. Used by :meth:`topological_equality`
        '''
        taken_b = set()
        b_substituents = list(other.substituents())
        cntr = 0
        for a_pos, a_substituent in self.substituents():
            matched = False
            cntr += 1
            for b_pos, b_substituent in b_substituents:
                if b_pos in taken_b:
                    continue
                if b_substituent == a_substituent:
                    matched = True
                    taken_b.add(b_pos)
                    break
            if not matched and cntr > 0:
                return False
        if len(taken_b) != len(b_substituents):
            return False
        return True

    def __eq__(self, other):
        '''
        Test for equality between :class:`Monosaccharide` instances.
        First try scalar equality of fields, and then compare descendants.
        '''
        if (other is None):
            return False
        if not isinstance(other, Monosaccharide):
            return False
        return self.exact_ordering_equality(other)

    def __ne__(self, other):
        return not (self == other)

    def __repr__(self):  # pragma: no cover
        return self.to_glycoct().replace("\n", ' ')

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        '''
        Does some testing to upgrade outdated, but equivalent
        modification models.
        '''
        self.anomer = state['_anomer']
        self.superclass = state['_superclass']
        self.stem = state['_stem']
        self.configuration = state['_configuration']

        self.ring_start = state['ring_start']
        self.ring_end = state['ring_end']
        self.id = state['id']

        self.modifications = state['modifications']
        self.links = state['links']
        self.substituent_links = state['substituent_links']
        self.composition = state["composition"]
        reduced = state.get('_reducing_end', None)
        # Make sure that if "aldi" is present, to replace it with
        # the default ReducedEnd
        if reduced is None:
            if self.modifications.popv(Modification.aldi) is not None:
                # Deduct the modification mass from the main composition
                self.composition -= {"H": 2}
                reduced = True
        self._reducing_end = None
        self.reducing_end = reduced

    def mass(self, substituents=True, average=False, charge=0, mass_data=None):
        '''
        Calculates the total mass of ``self``. If ``substituents=True`` it will include
        the masses of its substituents.

        Parameters
        ----------
        average: bool, optional, defaults to False
            Whether or not to use the average isotopic composition when calculating masses.
            When ``average == False``, masses are calculated using monoisotopic mass.
        charge: int, optional, defaults to 0
            If charge is non-zero, m/z is calculated, where m is the theoretical mass, and z is ``charge``
        mass_data: dict, optional
            If mass_data is None, standard NIST mass and isotopic abundance data are used. Otherwise the
            contents of mass_data are assumed to contain elemental mass and isotopic abundance information.
            Defaults to :const:`None`.

        Returns
        -------
        :class:`float`

        See also
        --------
        :func:`pygly2.composition.composition.calculate_mass`
        '''
        mass = calculate_mass(
            self.composition, average=average, charge=charge, mass_data=mass_data)
        if substituents:
            for link_pos, substituent_link, in self.substituent_links.items():
                mass += substituent_link[self].mass(
                    average=average, charge=charge, mass_data=mass_data)
        if self.reducing_end is not None:
            mass += self.reducing_end.mass(
                average=average, charge=charge, mass_data=mass_data)
        return mass

    def total_composition(self):
        '''
        Computes the sum of the composition of ``self`` and each of its linked
        :class:`~pygly2.structure.substituent.Substituent`s

        Returns
        -------
        :class:`~pygly2.composition.Composition`
        '''
        comp = self.composition.clone()
        for p, sub in self.substituents():
            comp += sub.total_composition()
        red_end = self.reducing_end
        if red_end is not None:
            comp += red_end.total_composition()
        return comp

    def children(self):
        '''
        Returns an iterator over the :class:`Monosaccharide` instancess which are considered
        the descendants of `self`.  Alias for `__iter__`
        '''
        for pos, link in self.links.items():
            if link.is_child(self):
                continue
            yield (pos, link.child)

    def parents(self):
        '''
        Returns an iterator over the :class:`Monosaccharide` instances which are considered
        the ancestors of `self`.
        '''
        for pos, link in self.links.items():
            if link.is_parent(self):
                continue
            yield (pos, link.parent)

    def substituents(self):
        '''
        Returns an iterator over all substituents attached1
        to :obj:`self` by a :class:`~.link.Link` object stored in :attr:`~.substituent_links`
        '''
        for pos, link in self.substituent_links.items():
            yield pos, link.to(self)

    def order(self, include_substituents=True):
        '''
        Return the "graph theory" order of this residue

        Parameters
        ----------
        include_substituents: bool
            Include the number of substituent_links in order calculations. Defaults to |True|

        Returns
        -------
        int
        '''
        return len(list(self.children())) + (len(self.substituent_links) if include_substituents else 0)

    def __iter__(self):
        return self.children()


class ReducedEnd(object):
    name = 'aldi'

    def __init__(self, composition=None, substituents=None, valence=2, id=None):
        if composition is None:
            composition = Composition("H2")
        else:
            composition = Composition(composition)
        self.composition = composition
        self.base_composition = self.composition.clone()
        self.links = substituents or OrderedMultiMap()
        self.valence = valence
        self.id = id or uuid4().int

    def is_occupied(self, position):
        '''
        Checks to see if a particular backbone position is occupied by a or :class:`.Substituent`.

        Parameters
        ----------
        position: int
            The position to check for occupancy. Passing -1 checks for undetermined attachments.

        Returns
        -------
        numeric:
            The number of occupants at ``position``, or `float('inf')` if `position` exceeds :attr:`valence`
        '''
        if position > self.valence:
            return float('inf')
        else:
            return len(self.links[position])

    def add_substituent(self, substituent, position=-1, max_occupancy=0,
                        child_position=1, parent_loss=None, child_loss=None):
        '''
        Adds a |Substituent| and associated |Link|
        to :attr:`substituent_links` at the site given by ``position``. This new substituent is included when
        calculating mass with substituents included

        Parameters
        ----------
        substituent: str or Substituent
            The substituent to add. If passed a |str|, it will be
            translated into an instance of |Substituent|
        position: int or 'x'
            The location to add the |Substituent| link to :attr:`substituent_links`. Defaults to -1
        child_position: int
            The location to add the link to in `substituent`'s :attr:`links`. Defaults to -1. Substituent
            indices are currently not checked.
        max_occupancy: int, optional
            The maximum number of items acceptable at ``position``. Defaults to :const:`1`
        parent_loss: Composition or str
            The elemental composition removed from ``self``
        child_loss: Composition or str
            The elemental composition removed from ``substituent``

        Raises
        ------
        IndexError
            ``position`` exceeds the bounds set by :attr:`superclass`.
        ValueError
            ``position`` is occupied by more than ``max_occupancy`` elements
        '''
        if self.is_occupied(position) > max_occupancy:
            raise ValueError("Site is already occupied")
        if child_loss is None:
            child_loss = Composition("H")
        if parent_loss is None:
            parent_loss = Composition("H")
        if isinstance(substituent, basestring):
            substituent = Substituent(substituent)
        Link(parent=self, child=substituent,
             parent_position=position, child_position=child_position,
             parent_loss=parent_loss, child_loss=child_loss)
        return self

    def drop_substituent(self, position, substituent=None, refund=True):
        '''
        Remove the `substituent` at `position`. 

        If `substituent` is |None|, then the first substituent found at `position` is
        removed. 

        Parameters
        ----------
        position: int
            The position to drop the modification from
        substituent: Substituent
            The |Substituent| to remove. If |None|, the first substituent found at
            `position` will be removed
        refund: bool
            Passed to :meth:`~.Link.break_link`

        Raises
        ------
        IndexError:
            If `position` exceeds :attr:`valence`

        ValueError:
            If `substituent` is not found at `position`

        Returns
        -------
        ReducedEnd:
            `self` for chaining calls
        '''
        if position > self.valence:
            raise IndexError("Index out of bounds")
        if isinstance(substituent, basestring):
            substituent = Substituent(substituent)
        link_obj = None
        for substituent_link in self.links[position]:
            if substituent_link.child.name == substituent.name or substituent is None:
                link_obj = substituent_link
                break
        if link_obj is None:
            if substituent is not None:
                msg = "No matching substituent found at {position}.".format(
                    position=position)
            else:
                msg = "No substituents found at {position}.".format(
                    position=position)
            raise IndexError(msg)

        link_obj.break_link(refund=refund)
        return self

    def mass(self, average=False, charge=0, mass_data=None):
        '''
        Calculates the total mass of ``self``.

        Parameters
        ----------
        average: bool, optional, defaults to False
            Whether or not to use the average isotopic composition when calculating masses.
            When ``average == False``, masses are calculated using monoisotopic mass.
        charge: int, optional, defaults to 0
            If charge is non-zero, m/z is calculated, where m is the theoretical mass, and z is ``charge``
        mass_data: dict, optional
            If mass_data is None, standard NIST mass and isotopic abundance data are used. Otherwise the
            contents of mass_data are assumed to contain elemental mass and isotopic abundance information.
            Defaults to :const:`None`.

        Returns
        -------
        :class:`float`

        See also
        --------
        :func:`pygly2.composition.composition.calculate_mass`
        '''
        mass = calculate_mass(
            self.composition, average=average, charge=charge, mass_data=mass_data)

        for pos, link in self.links.items():
            mass += link[self].mass(average=average, charge=charge, mass_data=mass_data)
        return mass

    def clone(self, prop_id=True):
        """Make a deep copy of `self`.
        
        Parameters
        ----------
        prop_id: bool
            Whether to copy over :attr:`id`.
        
        Returns
        -------
        ReducedEnd
        """
        result = ReducedEnd(
            Composition(self.base_composition), substituents=None,
            valence=self.valence, id=self.id if prop_id else None)
        for position, link in self.links.items():
            result.add_substituent(link.child.clone(), position)
        return result

    def children(self):
        '''
        Returns an iterator over the :class:`Monosaccharide`s which are considered
        the descendants of ``self``.
        '''
        for pos, link in self.links.items():
            if link.is_child(self):
                continue
            yield (pos, link.child)

    def total_composition(self):
        '''
        Computes the sum of the composition of `self` and each of its linked
        :class:`~.substituent.Substituent`s

        Returns
        -------
        :class:`~pygly2.composition.Composition`
        '''
        comp = self.composition
        for pos, sub in self.children():
            comp = comp + sub.total_composition()
        return comp

    def __repr__(self):  # pragma: no cover
        rep = "<ReducedEnd {}>".format(self.total_composition())
        return rep

    def __eq__(self, other):
        '''
        Test for equality with `other`, with special handling for `EnumValue` comparisons
        for dealing with legacy format objects. If compared to the string "aldi", returns |True|,
        otherwise does deep comparison of composition and substituents.
        '''
        if other is None:
            return False
        elif isinstance(other, (int, EnumValue)):
            return False
        elif isinstance(other, str):
            return other == self.name
        composition_equal = self.composition == other.composition
        if not composition_equal:
            return False
        for spair, opair in izip_longest(self.links.items(), other.links.items()):
            if spair[0] != opair[0]:
                return False
            if not spair[1]._flat_equality(opair[1]):
                return False
        return True

    def __ne__(self, other):
        return not self == other
