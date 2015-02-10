class EnumValue(object):
    '''Represents a wrapper around an value with a name to identify it and
    more rich comparison logic. A value of an enumerated type'''
    def __init__(self, group, name, value):
        self.name = intern(name)
        self.value = value
        self.group = group.__name__ if isinstance(group, EnumMeta) else group

    def __hash__(self):
        return hash(self.name)

    def __index__(self):
        return self.value

    def __eq__(self, other):
        if isinstance(other, EnumValue):
            if self.group != other.group:
                return False
            return self.value == other.value or self.name == other.value
        return self.value == other or self.name == other

    def __ne__(self, other):
        if isinstance(other, EnumValue) and self.group != other.group:
            return True
        return self.name != other or self.value != other

    def __repr__(self):
        return "<{group} {name}:{value}>".format(**self.__dict__)


class EnumMeta(type):
    '''
    A metaclass for types hosting enumerated members. Class attributes are
    automatically translated into ``EnumValue`` objects with the specified value
    and a name string matching the specified attribute name. Newly assigned attributes
    are wrapped dynamically.

    The class itself can be treated like a dictionary for looking up these attributes
    by name or value, and these values can be iterated over.

    ..note::
        Why is this necessary? It's probably not. I chose to write it initially for
        compatibility with a previous iteration of the library, but later decided it
        was worth keeping for two reasons:

        1. Avoids ``stringly-typing`` the library. Comparison of strings is a slippery slope
           to raw magic strings littering the codebase.
        2. Richer comparison behavior allows these same names to be used in different modes with the 
           same symbol.
        3. Namespacing of EnumValue objects makes it easier to avoid accidental name collisions
           when comparing EnumValues instead of magic strings.

    '''

    def __new__(cls, name, parents, attrs):
        for label, value in attrs.items():
            attrs[label] = EnumValue(name, label, value)

        return type.__new__(cls, name, parents, attrs)

    def __iter__(self):
        for attr, val in self.__dict__.items():
            if not attr.startswith("__") or attr == "mro":
                yield (attr, val)

    def __contains__(self, k):
        return (k in self.__dict__) or (k in self.__dict__.values())

    def __getitem__(self, k):
        return self.translate(k)

    def __setattr__(self, k, v):
        print(k, v)
        super(EnumMeta, self).__setattr__(k, EnumValue(self, k, v))

    def __setitem__(self, k, v):
        self.__setattr__(k, v)

    def translate(self, k):
        '''
        Attempt to translate the input object ``k`` into a data member of the Enum.

        If ``k`` is a :class:`str`, it will be converted to lower case.

        First try to find an element of ``self`` by hashing it against member names.
        
        Then try to find an element of ``self`` by searching for a member in self that
        is value-equal to ``k``

        Otherwise throw a :exc:`KeyError`

        Parameters
        ----------
        k: object
            The value to be translated.

        Returns
        -------
        :class:`EnumValue`

        '''
        try:
            k = k.lower()
        except:
            pass
        if k in self.__dict__:
            return self.__dict__[k]
        elif k in self:
            return self[self.name(k)]
        else:
            print("Could not translate {0} through {1}".format(k, self))
            raise KeyError(k)

    def name(self, v):
        for k, val in self:
            if v == val:
                return k

    def __repr__(self):
        return "<Enum {0}>".format(self.__name__)


class Enum(object):
    __metaclass__ = EnumMeta

    def __init__(self):
        raise Exception("This class is not meant to be instantiated. Reference its attribute members directly")
    