import operator
import logging
import itertools
import re
from functools import partial
from collections import deque, defaultdict, Callable
from uuid import uuid4

from .base import SaccharideBase
from .constants import RingType
from .monosaccharide import Monosaccharide, graph_clone, toggle as residue_toggle
from .crossring_fragments import enumerate_cleavage_pairs, crossring_fragments
from ..utils import make_counter, identity, StringIO, chrinc, make_struct
from ..composition import Composition

methodcaller = operator.methodcaller
logger = logging.getLogger("Glycan")

fragment_shift = {
    "B": Composition(O=1, H=2),
    "Y": Composition(),
    "C": Composition(),
    "Z": Composition(H=2, O=1),
}

fragment_direction = {
    "A": -1,
    "B": -1,
    "C": -1,
    "X": 1,
    "Y": 1,
    "Z": 1
}

MAIN_BRANCH_SYM = '-'

Fragment = make_struct(
    "Fragment", ("kind", "link_ids", "included_nodes", "mass", "name"))
'''
A simple container for a fragment ion, produced by :meth:`Glycan.fragments`

Created by :func:`make_struct`.

Attributes
----------
kind: |str|
    One of A, B, C, X, Y, or Z for each link broken or ring cleaved

link_ids: |list| of |int|
    The :attr:`id` value of each link cleaved.

included_nodes: |list| of |int|
    The :attr:`id` value of each |Monosaccharide| contained in the fragment

mass: |float|
    The mass or `m/z` of the fragment.

See Also
--------
:meth:`Glycan.fragments`
:func:`.make_struct`
'''


DisjointTrees = make_struct("DisjointTrees", ("parent_tree", "parent_include_nodes",
                                              "child_tree", "child_include_nodes", "link_ids"))


def fragment_to_substructure(fragment, tree):
    """Extract the substructure of `tree` which is contained in `fragment`


    >>> from pygly2 import glycans as glycan_factory
    >>> from pygly2.structure import glycan
    >>> n_linked_core = glycan_factory["N-Linked Core"]
    >>> frag = n_linked_core.fragments().next()
    >>> frag
    <Fragment kind=Y link_ids=[1] included_nodes=[1] mass=221.089937203>
    >>> glycan.fragment_to_substructure(frag, n_linked_core)
    RES
    1b:b-dglc-HEX-1:5
    2s:n-acetyl
    LIN
    1:1d(2+1)2n
    <BLANKLINE>
    >>>

    Parameters
    ----------
    fragment: Fragment
        The :class:`Fragment` to extract substructure for.
    tree: Glycan
        The |Glycan| to extract substructure from.

    Returns
    -------
    Glycan:
        The |Glycan| substructure defined by the nodes contained in `fragment` as
        found in `tree`
    """
    # Align the fragment locations with their id values.
    # Be aware that cross-ring cleavages are labeled differently.
    ion_types = re.findall(r"(\d+,\d+)?(\S)", fragment.kind)
    links_broken = fragment.link_ids

    pairings = zip(ion_types, links_broken)

    break_targets = [link_id for ion_type, link_id in pairings if ion_type[0] == ""]
    crossring_targets = {node_id: ion_type for ion_type, node_id in pairings if ion_type[0] != ""}

    # All operations will be done on a copy of the tree of interest
    tree = tree.clone()
    # A point of reference known to be inside the fragment tree
    anchor = None
    for pos, link in tree.iterlinks():
        # If the current link's child was cross-ring cleaved,
        # then we must apply that cleavage and find an anchor
        if link.child.id in crossring_targets:
            ion_type = crossring_targets[link.child.id]
            c1, c2 = map(int, ion_type[0].split(","))
            target = tree.get(link.child.id)
            a_frag, x_frag = crossring_fragments(target, c1, c2, attach=True, copy=False)
            residue_toggle(target).next()

            for pos, link in a_frag.links.items():
                if link[a_frag].id in fragment.included_nodes:
                    anchor = a_frag

            for pos, link in x_frag.links.items():
                if link[x_frag].id in fragment.included_nodes:
                    anchor = x_frag
        # If this link was cleaved, break it and find an anchor
        if link.id in break_targets:
            parent, child = link.break_link(refund=True)
            if parent.id in fragment.included_nodes:
                anchor = parent
            elif child.id in fragment.included_nodes:
                anchor = child

    # Build a new tree from the anchor
    substructure = Glycan(root=anchor, index_method=None).reroot()

    return substructure


class Glycan(SaccharideBase):

    '''
    Represents a full graph of connected |Monosaccharide| objects and their connecting bonds.

    Attributes
    ----------
    root: |Monosaccharide|
        The first monosaccharide unit of the glycan, and the reducing end if present.
    index: |list|
        A list of the |Monosaccharide| instances in `self` in the order they are encountered
        by traversal by `traversal_methods[index_method]`
    link_index: |list|
        A list of the |Link| connecting the |Monosaccharide| instances in `self` in the order they
        are encountered by traversal by `traversal_methods[index_method]`
    reducing_end: |int| or |None|
        The index of the reducing end on :attr:`root`.
    branch_lengths: |dict|
        A dictionary mapping branch symbols to their lengths
    '''

    @classmethod
    def subtree_from(cls, tree, node, visited=None):
        if isinstance(node, int):
            node = tree[node]
        visited = {
            node.id for p,
            node in node.parents()} if visited is None else visited
        subtree = cls(root=node, index_method=None).clone(
            index_method=None, visited=visited)
        return subtree

    traversal_methods = {}

    def __init__(self, root=None, index_method='dfs'):
        '''
        Constructs a new Glycan from the collection of connected |Monosaccharide| objects
        rooted at `root`.

        If index_method is not |None|, the graph is indexed by the default search method
        given by `traversal_methods[index_method]`
        '''
        if root is None:
            root = Monosaccharide()
        self.root = root
        self.index = []
        self.link_index = []
        self.branch_lengths = {}
        if index_method is not None:
            self.reindex(index_method)

    def reindex(self, method='dfs'):
        '''
        Traverse the graph using the function specified by ``method``. The order of
        traversal defines the new :attr:`id` value for each |Monosaccharide|
        and |Link|.

        The order of traversal also defines the ordering of the |Monosaccharide|
        in :attr:`index` and |Link| in :attr:`link_index`.

        '''
        self.deindex()
        traversal = self._get_traversal_method(method)
        index = []
        i = 1
        for node in traversal():
            index.append(node)
        for node in index:
            node.id = i
            i += 1

        link_index = []
        for pos, link in self.iterlinks(method=method):
            link_index.append(link)

        i = 1
        for link in link_index:
            link.id = i
            i += 1

        self.index = index
        self.link_index = link_index

        self.label_branches()

        return self

    def deindex(self):
        '''
        When combining two Glycan structures, very often their component ids will
        overlap, making it impossible to differentiate between a cycle and the new
        graph. This function mangles all of the node and link ids so that they are
        distinct from the pre-existing nodes.
        '''
        if self.index is not None and len(self.index) > 0:
            base = uuid4().int
            for node in self.index:
                node.id += base
                node.id *= -1
            for link in self.link_index:
                link.id += base
                link.id *= -1
        return self

    def reroot(self):
        '''
        Set :attr:`root` to the node with the lowest :attr:`id`
        '''
        self.root = sorted(self, key=operator.attrgetter('id'))[0]
        self.reindex()
        return self

    def __getitem__(self, ix):
        '''
        Alias for :attr:`index.__getitem__`
        '''
        if self.index is not None:
            return self.index[ix]
        else:
            raise IndexError("Tried to access the index of an unindexed Glycan.")

    def get(self, ix):
        for node in self:
            if node.id == ix:
                return node
        else:
            raise IndexError("Could not find a node with the given id {}".format(ix))

    @property
    def root(self):
        return self._root

    @root.setter
    def root(self, value):
        self._root = value

    @property
    def reducing_end(self):
        '''
        An alias for :attr:`Monosaccharide.reducing_end` for :attr:`root`
        '''
        return self.root.reducing_end

    @reducing_end.setter
    def reducing_end(self, value):
        self.root.reducing_end = value

    def set_reducing_end(self, value):
        '''
        Sets the reducing end type, and configures the root residue appropriately.

        If the reducing_end is not |None|, then the following state changes are made to the root:

        .. code-block:: python

            self.root.ring_start = 0
            self.root.ring_end = 0
            self.root.anomer = "uncyclized"

        Else, the correct state is unknown:

        .. code-block:: python

            self.root.ring_start = None
            self.root.ring_end = None
            self.root.anomer = None

        '''
        self.root.reducing_end = value
        if self.reducing_end is not None:
            self.root.ring_start = 0
            self.root.ring_end = 0
            self.root.anomer = "uncyclized"
        else:
            self.root.ring_start = None
            self.root.ring_end = None
            self.root.anomer = None

    def depth_first_traversal(self, from_node=None, apply_fn=identity, visited=None):
        '''
        Make a depth-first traversal of the glycan graph. Children are explored in descending bond-order.

        This is the default traversal method for all |Glycan| objects. :meth:`~.dfs` is an alias of this method.
        Both names can be used to specify this strategy to :meth:`~._get_traversal_method`.

        Parameters
        ----------
        from_node: None or Monosaccharide
            If `from_node` is |None|, then traversal starts from the root node. Otherwise it begins
            from the given node.
        apply_fn: function
            A function applied to each node on arrival. If this function returns a non-None value,
            the result is yielded from the generator, otherwise it is ignored. Defaults to :func:`.identity`
        visited: set or None
            A :class:`set` of node ID values to ignore. If |None|, defaults to the empty `set`

        Yields
        ------
        Return Value of `apply_fn`, by default |Monosaccharide|

        See also
        --------
        Glycan.breadth_first_traversal
        '''
        sort_predicate = methodcaller("order")
        node_stack = list([self.root if from_node is None else from_node])
        visited = set() if visited is None else visited
        while len(node_stack) > 0:
            node = node_stack.pop()
            visited.add(node.id)
            res = apply_fn(node)
            if res is not None:
                yield res
            node_stack.extend(sorted((terminal for pos, link in node.links.items()
                                      for terminal in link if terminal.id not in visited), key=sort_predicate))

    # Convenience aliases and the set up the traversal_methods entry
    dfs = depth_first_traversal
    traversal_methods['dfs'] = "dfs"
    traversal_methods['depth_first_traversal'] = "dfs"

    def breadth_first_traversal(
            self, from_node=None, apply_fn=identity, visited=None):
        '''
        Make a breadth-first traversal of the glycan graph. Children are explored in descending bond-order.

        :meth:`~.bfs` is an alias of this method.
        Both names can be used to specify this strategy to :meth:`~._get_traversal_method`.

        Parameters
        ----------
        from_node: None or Monosaccharide
            If `from_node` is |None|, then traversal starts from the root node. Otherwise it begins
            from the given node.
        apply_fn: function
            A function applied to each node on arrival. If this function returns a non-None value,
            the result is yielded from the generator, otherwise it is ignored. Defaults to :func:`.identity`
        visited: set or None
            A :class:`set` of node ID values to ignore. If |None|, defaults to the empty `set`

        Yields
        ------
        Return Value of `apply_fn`, by default |Monosaccharide|

        See also
        --------
        Glycan.depth_first_traversal
        '''
        sort_predicate = methodcaller("order")
        node_queue = deque([self.root if from_node is None else from_node])
        visited = set() if visited is None else visited
        while len(node_queue) > 0:
            node = node_queue.popleft()
            visited.add(node.id)
            res = apply_fn(node)
            if res is not None:
                yield res
            node_queue.extend(sorted((terminal for pos, link in node.links.items()
                                      for terminal in link if terminal.id not in visited), key=sort_predicate))

    # Convenience aliases and the set up the traversal_methods entry
    bfs = breadth_first_traversal
    traversal_methods['bfs'] = "bfs"
    traversal_methods['breadth_first_traversal'] = "bfs"

    def _get_traversal_method(self, method):
        if method == 'dfs':
            return self.dfs
        elif method == 'bfs':
            return self.bfs
        elif isinstance(method, Callable):
            return partial(method, self)
        traversal = self.traversal_methods.get(method, None)
        if traversal is None:
            raise AttributeError("Unknown traversal method: {}".format(method))
        traversal = getattr(self, traversal)
        return traversal

    def __iter__(self):
        return self.iternodes()

    def iternodes(
            self, from_node=None, apply_fn=identity, method='dfs', visited=None):
        '''
        Generic iterator over nodes. :meth:`Glycan.__iter__` is an alias of this method

        Parameters
        ----------
        from_node: None or Monosaccharide
            If `from_node` is |None|, then traversal starts from the root node. Otherwise it begins
            from the given node.
        apply_fn: function
            A function applied to each node on arrival. If this function returns a non-None value,
            the result is yielded from the generator, otherwise it is ignored. Defaults to :func:`.identity`
        method: str or `function`
            Traversal method to use. See :meth:`._get_traversal_method`
        visited: set or None
            A :class:`set` of node ID values to ignore. If |None|, defaults to the empty `set`

        Yields
        ------
        Return Value of `apply_fn`, by default Monosaccharide

        See also
        --------
        depth_first_traversal
        breadth_first_traversal
        _get_traversal_method
        '''
        traversal = self._get_traversal_method(method)
        return traversal(
            from_node=from_node, apply_fn=apply_fn, visited=visited)

    def iterlinks(self, substituents=False, method='dfs', visited=None):
        '''
        Iterates over all |Link| objects in |Glycan|.

        Parameters
        ----------
        substituents: bool
            If `substituents` is |True|, then include the |Link| objects in
            :attr:`substituent_links` on each |Monosaccharide|
        method: str or function
            The traversal method controlling the order of the nodes visited
        visited: None or set
            The collection of id values to ignore when traversing

        Yields
        ------
        Link
        '''
        traversal = self._get_traversal_method(method)
        links_visited = set()

        def links(obj):
            if substituents:
                for pos, link in obj.substituent_links.items():
                    yield (pos, link)
            for pos, link in obj.links.items():
                if link.id in links_visited:
                    continue
                links_visited.add(link.id)
                yield (pos, link)

        return itertools.chain.from_iterable(
            traversal(apply_fn=links, visited=visited))

    def leaves(self, bidirectional=False, method='dfs', visited=None):
        '''
        Iterates over all |Monosaccharide| objects in |Glycan|, yielding only those
        that have no child nodes.

        Parameters
        ----------
        bidirectional: bool
            If `bidirectional` is |True|, then only |Monosaccharide| objects
            with only one entry in :attr:`links`.
        method: str or function
            The traversal method controlling the order of the nodes visited
        visited: None or set
            The collection of id values to ignore when traversing

        Yields
        ------
        |Monosaccharide|
        '''
        traversal = self._get_traversal_method(method)
        if bidirectional:
            def is_leaf(obj):
                if len(obj.links) == 1:
                    yield obj
        else:
            def is_leaf(obj):
                if len(list(obj.children())) == 0:
                    yield obj

        return itertools.chain.from_iterable(
            traversal(apply_fn=is_leaf, visited=visited))

    def label_branches(self):
        '''
        Labels each branch point with an alphabetical symbol. Also computes and stores each branch's
        length and stores it in :attr:`branch_lengths`
        '''
        last_branch_label = MAIN_BRANCH_SYM
        self.branch_lengths = {MAIN_BRANCH_SYM: 0}

        def get_parent_link(node):
            try:
                label = node.links[node.parents().next()[0]][0].label
                if label is None:
                    return MAIN_BRANCH_SYM
                else:
                    return label[0]
            except StopIteration:
                return MAIN_BRANCH_SYM

        for node in self:
            links = []
            for pos, link in node.links.items():
                if link.is_child(node):
                    continue
                links.append(link)
            if len(links) == 1:
                label_key = get_parent_link(node)
                self.branch_lengths[label_key] += 1
                label = "{}{}".format(
                    label_key, self.branch_lengths[label_key])
                links[0].label = label
            else:
                last_label_key = label_key = get_parent_link(node)
                count = self.branch_lengths[last_label_key]
                for link in links:
                    last_branch_label = chrinc(
                        last_branch_label) if last_branch_label != MAIN_BRANCH_SYM else 'a'
                    new_label_key = last_branch_label
                    self.branch_lengths[new_label_key] = count + 1
                    label = "{}{}".format(
                        new_label_key, self.branch_lengths[new_label_key])
                    link.label = label
        self.branch_lengths["-"] = max(self.branch_lengths.values())

    def count_branches(self):
        '''
        Count the number of branches in the Glycan tree

        Returns
        -------
        int
        '''
        count = 0
        for node in self:
            if len(node.links) > 2:
                count += 2 if count == 0 else 1
        return count

    def order(self):
        '''
        The number of nodes in the graph. :meth:`__len__` is an alias of this

        Returns
        -------
        int
        '''
        count = 0
        for node in self:
            count += 1
        return count

    __len__ = order

    def to_glycoct(self, buffer=None, close=False):
        '''
        Serialize the |Glycan| graph object into condensed GlycoCT, using
        `buffer` to store the result. If `buffer` is |None|, then the
        function will operate on a newly created :class:`~pygly2.utils.StringIO` object.

        Parameters
        ----------
        buffer: file-like or None
            The stream to write the serialized structure to. If |None|, uses an instance
            of `StringIO`
        close: bool
            Whether or not to close the stream in `buffer` after writing is done

        Returns
        -------
        file-like or str if ``buffer`` is :const:`None`

        '''
        is_stringio = False
        if buffer is None:
            buffer = StringIO()
            is_stringio = True

        buffer.write("RES\n")

        res_counter = make_counter()
        lin_counter = make_counter()

        # Look-ups for mapping RES nodes to objects by section index and id,
        # respectively
        index_to_residue = {}
        residue_to_index = {}

        # Accumulator for linkage indices and mapping linkage indices to
        # dependent RES indices
        lin_accumulator = []
        dependencies = defaultdict(dict)

        for node in (self):
            res, lin, index = node.to_glycoct(
                res_counter, lin_counter, complete=False)

            lin_accumulator.append((index, lin))
            residue_to_index[node.id] = index
            index_to_residue[index] = node

            for pos, link in node.links.items():
                if link.is_child(node):
                    continue
                dependencies[link.child.id][node.id] = ((lin_counter(), link))
            for line in res:
                buffer.write(line + '\n')

        buffer.write("LIN\n")
        for res_ix, links in lin_accumulator:
            for line in links:
                buffer.write(line + '\n')
            residue = index_to_residue[res_ix]
            for pos, link in residue.links.items():
                if link.is_child(residue):
                    continue
                child_res = link.child
                ix, link = dependencies[child_res.id][residue.id]
                buffer.write(
                    link.to_glycoct(ix, res_ix, residue_to_index[child_res.id]) + "\n")

        if is_stringio:
            return buffer.getvalue()
        else:  # pragma: no cover
            if close:
                buffer.close()
            return buffer

    __repr__ = to_glycoct

    def mass(self, average=False, charge=0, mass_data=None):
        '''
        Calculates the total mass of the intact graph by querying each
        node for its mass.

        Parameters
        ----------
        average: bool, optional, defaults to False
            Whether or not to use the average isotopic composition when calculating masses.
            When ``average == False``, masses are calculated using monoisotopic mass.
        charge: int, optional, defaults to 0
            If charge is non-zero, m/z is calculated, where m is the theoretical mass, and z is `charge`
        mass_data: dict, optional, defaults to None
            If mass_data is None, standard NIST mass and isotopic abundance data are used. Otherwise the
            contents of mass_data are assumed to contain elemental mass and isotopic abundance information.


        Returns
        -------
        float

        See also
        --------
        :func:`pygly2.composition.composition.calculate_mass`
        '''
        return sum(
            node.mass(average=average, charge=charge, mass_data=mass_data) for node in self)

    def total_composition(self):
        '''
        Computes the sum of the composition of all |Monosaccharide| objects in ``self``

        Returns
        -------
        :class:`~pygly2.composition.Composition`
        '''

        return sum((node.total_composition() for node in self), Composition())

    def clone(self, index_method='dfs', visited=None):
        '''
        Create a copy of `self`, indexed using `index_method`, a *traversal method*  or |None|.

        Returns
        -------
        :class:`~pygly2.structure.glycan.Glycan`
        '''
        clone_root = graph_clone(self.root, visited=visited)
        return Glycan(clone_root, index_method=index_method)

    def __eq__(self, other):
        '''
        Two glycans are considered equal if they are identically ordered nodes.

        Parameters
        ----------
        self, other: :class:`~pygly2.structure.glycan.Glycan`

        Returns
        -------
        bool

        See also
        --------
        :meth:`pygly2.structure.Monosaccharide.exact_ordering_equality`
        '''
        if other is None:
            return False
        elif not isinstance(other, Glycan):
            return False
        return self.root.exact_ordering_equality(other.root)

    def topological_equality(self, other):
        '''
        Two glycans are considered equal if they are topologically equal.

        Parameters
        ----------
        self, other: :class:`~pygly2.structure.glycan.Glycan`

        Returns
        -------
        bool

        See also
        --------
        :meth:`pygly2.structure.Monosaccharide.topological_equality`
        '''
        return self.root.topological_equality(other.root)

    def __ne__(self, other):
        return not self == other

    def fragments(self, kind=('B', 'Y'), max_cleavages=1, average=False, charge=0, mass_data=None,
                  min_cleavages=1, inplace=False, visited=None):
        '''
        Generate carbohydrate backbone fragments from this glycan by examining the disjoint subtrees
        created by removing one or more monosaccharide-monosaccharide bond.

        .. note::
            While generating fragments with `inplace = True`, the |Glycan| object is being permuted. All of the
            changes being made are reversed during the generation process, and the glycan is
            returned to the same state it was in when :meth:`~.fragments` was called by the end
            of the generator. Do not attempt to use the |Glycan| object for other things while
            fragmenting it. If you must, copy it first with :meth:`~.clone`.


        Parameters
        ----------
        kind: `sequence`
            Any `iterable` or `sequence` of characters corresponding to A/B/C/X/Y/Z
            as published by :title-reference:`Domon and Costello`
        max_cleavages: |int|
            The maximum number of bonds to break per fragment
        average: bool, optional, defaults to `False`
            Whether or not to use the average isotopic composition when calculating masses.
            When ``average == False``, masses are calculated using monoisotopic mass.
        charge: int, optional, defaults to 0
            If charge is non-zero, m/z is calculated, where m is the theoretical mass, and z is `charge`
        mass_data: dict, optional, defaults to `None`
            If mass_data is |None|, standard NIST mass and isotopic abundance data are used. Otherwise the
            contents of `mass_data` are assumed to contain elemental mass and isotopic abundance information.
        inplace: `bool`
            Whether or not to first copy `self` and generate fragments from the copy, keeping `self` intact.

        Yields
        ------
        :class:`Fragment`

        See also
        --------
        :func:`pygly2.composition.composition.calculate_mass`
        '''
        gen = self
        if not inplace:
            gen = self.clone()
        results_container = Fragment
        for i in range(min_cleavages, max_cleavages + 1):
            for kind, link_ids, included_nodes, mass in gen.break_links(i, kind, average, charge, mass_data, visited=visited):
                frag = results_container(kind, link_ids, included_nodes, mass, None)
                try:
                    frag.name = self.name_fragment(frag)
                except:
                    frag.name = str(frag)
                yield frag

    def break_links(self, n_links=0, kind=(
            'B', 'Y'), average=False, charge=0, mass_data=None, visited=None):
        '''
        A recursive co-routine that generates all `kind` fragments of a glycan graph to a
        depth of `n_links`. If `n_links` > 1, then internal fragments are generated.

        Called by :meth:`Glycan.fragments`

        Parameters
        ----------
        n_links: int
            The number of bonds remaining to break for each fragment generated
        kind: sequence of strings
            An iterable containing any entries of "ABCXYZ", which select the Domon and Costello
            fragment types to generate.
        average: bool
            Generate masses based on average isotopic composition? Defaults to |False|
        charge: int
            Generate m/z instead of neutral mass where this value is z, z != 0. Defaults to 0
            which results in theoretical neutral mass
        mass_data: dict
            If mass_data is |None|, standard NIST mass and isotopic abundance data are used. Otherwise
            the contents of `mass_data` are assumed to contain elemental mass and isotopic abundance information
        visited: set
            A set of link ids to not visit by :meth:`iterlinks`. If |None| will be the empty set.


        Yields
        ------
            ion_type: str
                The string identifying the types of cleavages involved in creating this fragment
            link_ids: list
                A list of the link ids and crossring-cleaved residue ids involved in creating
                this fragment
            include: list
                A list of the |Monosaccharide| id values included in this fragment
            mass: float
                The mass or m/z of the fragment

        '''
        if n_links < 0:  # pragma: no cover
            raise ValueError("Cannot break a negative number of Links")
        n_links -= 1
        kind = set(kind)
        if visited is None:
            visited = set()
        for pos, link in self.iterlinks():
            try:
                if link.id in visited:
                    continue
                if not link.is_attached():
                    continue
                parent, child = link.break_link(refund=True)
                break_id = link.id
                logger.debug("Breaking %d", break_id)
                parent_tree = Glycan(root=parent, index_method=None)
                child_tree = Glycan(root=child, index_method=None)

                # If there are more cleavages to make,
                if n_links > 0:
                    # Recursively call :meth:`break_link` with the decremented `n_links` counter,
                    # and propagate all other parameters.
                    parent_frags = list(parent_tree.break_links(
                        n_links, kind=kind, average=average, charge=charge, mass_data=mass_data, visited=visited))
                    child_frags = list(child_tree.break_links(
                        n_links, kind=kind, average=average, charge=charge, mass_data=mass_data, visited=visited))

                    for k in (kind) & set("YZ"):
                        offset = fragment_shift[k].calc_mass(
                            average=average, mass_data=mass_data)
                        for ion_type, link_ids, include, mass in parent_frags:
                            yield ion_type + k, link_ids + [break_id], include, mass - offset

                    for k in (kind) & set("BC"):
                        offset = fragment_shift[k].calc_mass(
                            average=average, mass_data=mass_data)
                        for ion_type, link_ids, include, mass in child_frags:
                            yield ion_type + k, link_ids + [break_id], include, mass - offset

                    # If generating crossring cleavages
                    ring_type = child.ring_type
                    if len((kind) & set("AX")) > 0 and ring_type is not RingType.x and ring_type is not RingType.open:
                        # Re-apply the broken link temporarily
                        link.apply()
                        try:
                            # For each pair of cleavage sites available
                            for c1, c2 in enumerate_cleavage_pairs(child):
                                # Generate both A and X fragments of the child residue
                                a_fragment, x_fragment = crossring_fragments(child, c1, c2, copy=False)
                                # Mask the child residue so that only its fragments are bound
                                # to the glycan graph
                                child_link_mask = residue_toggle(child)
                                child_link_mask.next()
                                if "A" in kind:
                                    a_tree = Glycan(a_fragment, index_method=None)
                                    # Recursively generate fragments from crossring cleavage-bound subtree
                                    for ion_type, link_ids, include, mass in a_tree.break_links(
                                            n_links, kind=kind, average=average, charge=charge,
                                            mass_data=mass_data, visited=visited):
                                        yield ion_type + '{},{}A'.format(c1, c2), link_ids + [child.id], include, mass
                                # Remove all links connecting subtrees through A fragment.
                                # logger.debug("Releasing %r", a_fragment)
                                a_fragment.release()

                                if "X" in kind:
                                    x_tree = Glycan(x_fragment, index_method=None)
                                    # Recursively generate fragments from crossring cleavage-bound subtree
                                    for ion_type, link_ids, include, mass in x_tree.break_links(
                                            n_links, kind=kind, average=average, charge=charge,
                                            mass_data=mass_data, visited=visited):
                                        yield ion_type + '{},{}X'.format(c1, c2), link_ids + [child.id], include, mass
                                # Remove all links connecting subtrees trough the X fragment.
                                # logger.debug("Releasing %r", x_fragment)
                                x_fragment.release()

                                # Unmask the original residue, re-connecting all of its subtrees
                                child_link_mask.next()
                        finally:
                            # Re-break the link for release in the later `finally` block
                            if link.is_attached():
                                link.break_link(refund=True)
                else:
                    parent_include = [n.id for n in parent_tree]
                    child_include = [n.id for n in child_tree]

                    for k in (kind) & set("YZ"):
                        offset = fragment_shift[k].calc_mass(
                            average=average, mass_data=mass_data)
                        mass = parent_tree.mass(
                            average=average, charge=charge, mass_data=mass_data) - offset
                        yield (k, [break_id], parent_include, mass)

                    for k in (kind) & set("BC"):
                        offset = fragment_shift[k].calc_mass(
                            average=average, mass_data=mass_data)
                        mass = child_tree.mass(
                            average=average, charge=charge, mass_data=mass_data) - offset
                        yield (k, [break_id], child_include, mass)

                    ring_type = child.ring_type
                    if len((kind) & set("AX")) > 0 and ring_type is not RingType.x and ring_type is not RingType.open:
                        # Re-apply the broken link temporarily
                        link.apply()
                        try:
                            # For each pair of cleavage sites available
                            for c1, c2 in enumerate_cleavage_pairs(child):
                                # Generate crossring fragments
                                a_fragment, x_fragment = crossring_fragments(child, c1, c2, copy=False)
                                # Mask child residue, connecting subtrees only through the
                                # fragments
                                child_link_mask = residue_toggle(child)
                                child_link_mask.next()
                                if "A" in kind:
                                    a_tree = Glycan(a_fragment, index_method=None)
                                    a_include = [n.id for n in a_tree]
                                    # Only yield crossring fragments that include more than
                                    # the fragment residue itself
                                    if len(a_include) > 1:
                                        yield '{},{}A'.format(c1, c2), [child.id],\
                                            a_include, a_tree.mass(
                                                average=average, charge=charge, mass_data=mass_data)
                                # logger.debug("Releasing %r", a_fragment)
                                a_fragment.release()

                                if "X" in kind:
                                    x_tree = Glycan(x_fragment, index_method=None)
                                    x_include = [n.id for n in x_tree]
                                    # Only yield crossring fragments that include more than
                                    # the fragment residue itself
                                    if len(x_include) > 1:
                                        yield '{},{}X'.format(c1, c2), [child.id],\
                                            x_include, x_tree.mass(
                                                average=average, charge=charge, mass_data=mass_data)
                                # logger.debug("Releasing %r", x_fragment)
                                x_fragment.release()

                                child_link_mask.next()
                        finally:
                            if link.is_attached():
                                link.break_link(refund=True)

            finally:
                # Unmask the Link and apply its composition shifts
                if not link.is_attached():
                    logger.debug("Reapplying %d", link.id)
                    link.apply()

    def substructures(self, max_cleavages=1, min_cleavages=1, min_size=2):
        '''
        Generate disjoint subtrees from this glycan by examining by removing one or
        more monosaccharide-monosaccharide bond.

        .. note::
            While generating substructures, the glycan object is being permuted. All of the
            changes being made are reversed during the generation process, and the glycan is
            returned to the same state it was in when :meth:`~.substructures` was called by the end
            of the generator. Do not attempt to use the glycan object for other things while
            fragmenting it. If you must, copy it first with :meth:`~.clone`.


        Parameters
        ----------
        max_cleavages: |int|
            The maximum number of bonds to break per substructure
        min_cleavages: |int|
            The minimum number of bonds to break per substructure
        min_size: |int|
            The minimum number of monosaccharides per substructure

        See also
        --------
        :func:`pygly2.composition.composition.calculate_mass`
        '''
        results_container = DisjointTrees
        for frag in self.break_links_subtrees(
                max_cleavages, min_size=min_size):
            yield results_container(*frag)

    def break_links_subtrees(self, n_links, min_size):
        if n_links < 0:  # pragma: no cover
            raise ValueError("Cannot break a negative number of Links")
        n_links -= 1
        for pos, link in self.iterlinks():
            try:
                parent, child = link.break_link(refund=True)
                break_id = link.id
                logger.debug("Breaking %d", break_id)

                parent_tree = Glycan(root=parent, index_method=None)
                child_tree = Glycan(root=child, index_method=None)
                parent_include = [n.id for n in parent_tree.dfs()]
                child_include = [n.id for n in child_tree.dfs()]

                # Copy the trees so that when the Link object is unmasked the copies returned
                # to the user are not suddenly joined again.
                parent_clone = parent_tree.clone(index_method=None).reroot()
                child_clone = child_tree.clone(index_method=None).reroot()
                if parent_clone.order(
                ) > min_size or child_clone.order() > min_size:
                    yield (parent_clone, parent_include, child_clone, child_include, [break_id])
                if n_links > 0:
                    logger.debug("%d more links to break", n_links)
                    if parent_tree.order() > min_size:
                        for p_parent, parent_include, p_child, child_include, p_link_ids in parent_tree.break_links_subtrees(
                                n_links, min_size=min_size):
                            yield p_parent, parent_include, p_child, child_include, p_link_ids + [break_id]

                    if child_tree.order() > min_size:
                        for c_parent, parent_include, c_child, child_include, c_link_ids in child_tree.break_links_subtrees(
                                n_links, min_size=min_size):
                            yield c_parent, parent_include, c_child, child_include, c_link_ids + [break_id]
            finally:
                # Unmask the Link and apply its composition shifts
                logger.debug("Reapplying %d", break_id)
                link.apply()

    def name_fragment(self, fragment):
        '''
        Attempt to assign a full name to a fragment based on the branch and position relative to
        the reducing end along side A/B/C/X/Y/Z, according to :title-reference:`Domon and Costello`
        '''
        ring_coordinates, ion_kind = re.search(r"(\d+,\d+)?(\S)", fragment.kind).groups()
        ring_coordinates = "" if ring_coordinates is None else ring_coordinates

        ion_types = re.findall(r"(\d+,\d+)?(\S)", fragment.kind)
        links_broken = fragment.link_ids

        pairings = zip(ion_types, links_broken)

        break_targets = {link_id: ion_type for ion_type, link_id in pairings if ion_type[0] == ""}
        crossring_targets = {node_id: ion_type for ion_type, node_id in pairings if ion_type[0] != ""}

        # Accumulator for name components
        name_parts = []

        # Collect cross-ring fragment names
        for crossring_id in crossring_targets:
            # Seek the link that holds the fragmented residue
            for link in self.link_index:
                if link.child.id == crossring_id:
                    ion_type = crossring_targets[crossring_id]
                    label = link.label
                    if fragment_direction[ion_type[1]] > 0:
                        name = "{}{}".format(''.join(map(str, ion_type)), label.replace(MAIN_BRANCH_SYM, ""))
                        name_parts.append(name)
                    else:
                        label_key = label[0]
                        distance = int(label[1:])
                        inverted_distance = self.branch_lengths[label_key] - (distance - 1)
                        name = "{}{}{}".format(''.join(map(str, ion_type)), label_key.replace(MAIN_BRANCH_SYM, ""), inverted_distance)
                        name_parts.append(name)
                    break

        # Collect glycocidic fragment names
        for break_id, ion_type in break_targets.items():
            ion_type = ion_type[1]
            if fragment_direction[ion_type] > 0:
                link = self.link_index[break_id - 1]
                label = link.label
                name = "{}{}".format(ion_type, label.replace(MAIN_BRANCH_SYM, ""))
                name_parts.append(name)
            else:
                link = self.link_index[fragment.link_ids[0] - 1]
                label = link.label
                label_key = label[0]
                distance = int(label[1:])
                inverted_distance = self.branch_lengths[label_key] - (distance - 1)
                name = "{}{}{}".format(
                    ion_type, label_key.replace(MAIN_BRANCH_SYM, ""), inverted_distance)
                name_parts.append(name)

        return '-'.join(name_parts)
