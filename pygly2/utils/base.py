import sys
import gzip

def opener(obj, mode='r'):
    '''
    Try to use `obj` to access a file-object. If `obj` is a string, assume
    it denotes a path to a file, and open that file in the specified mode.
    If `obj` has an attribute `read`, assume it
    itself is a file-like object and return it.

    Parameters
    ----------
    obj: basestring or file-like object
        If `obj` is a base string it is treated like a file path, else if it supports
        the file-like operation `read`, return the object unchanged.
    mode: str, optional
        The mode, if any, to open `obj` with if it is a file path. Defaults to 'r', `read`

    '''
    if isinstance(obj, basestring):
        if obj[-2:] == 'gz':
            return gzip.open(obj, mode)
        return open(obj, mode)
    elif hasattr(obj, "read"):
        return obj
    else:
        raise IOError("Can't find a way to open {}".format(obj))


def invert_dict(d):
    return {v: k for k, v in d.items()}


def make_counter(start=1, label=""):
    '''
    Create a functor whose only internal piece of data is a mutable container
    with a reference to an integer, `start`. When the functor is called, it returns
    current `int` value of `start` and increments the mutable value by one.

    Parameters
    ----------
    start: int, optional
        The number to start counting from. Defaults to `1`.
    return: int
        The next number in the count progression.
    '''
    start = [start]

    def count_up():
        ret_val = start[0]
        start[0] += 1
        return ret_val
    return count_up


def identity(x):   # pragma: no cover
    return x


def nullop(*args, **kwargs):   # pragma: no cover
    pass


def chrinc(a='a', i=1):
    return chr(ord(a) + i)


def make_struct(name, fields):
    '''
    A convenience function for defining plain-old-data (POD) objects that are optimized
    for named accessor lookup, unlike `namedtuple`. If the named container does not
    require any special logic and won't be extended, the resulting structure is best for
    storing and accessing the data.
    '''
    template = ('''
class {name}(object):
    __slots__ = {fields!r}
    def __init__(self, {args}):
        {self_fields} = {args}
    def __getitem__(self, idx):
        return getattr(self, fields[idx])
    def __getstate__(self):
        return ({self_fields})
    def __setstate__(self, state):
        {self_fields} = state
    def __repr__(self):
        rep = "<{name}"
        for f in {fields!r}:
            rep += " " + f + "=" + str(getattr(self, f))
        rep += ">"
        return rep
    def __eq__(self, other):
        for f in {fields!r}:
            if getattr(self, f) != getattr(other, f):
                return False
        return True
    def __ne__(self, other):
        return not self == other

    @property
    def __dict__(self):
        d = dict()
        for f in {fields!r}:
            d[f] = getattr(self, f)
        return d
    ''').format(
        name=name,
        fields=fields,
        args=','.join(fields),
        self_fields=','.join('self.' + f for f in fields))
    d = {'fields': fields}
    exec(template, d)
    result = d[name]
    # Patch the class to support pickling, as is done for namedtuple
    try:
        result.__module__ = sys._getframe(1).f_globals.get('__name__', '__main__')
    except (AttributeError, ValueError):  # pragma: no cover
        pass
    return result


class ClassPropertyDescriptor(object):
    '''
    Standard Class Property Descriptor Implementation
    '''
    def __init__(self, fget, fset=None):
        self.fget = fget
        self.fset = fset

    def __get__(self, obj, klass=None):
        if klass is None:
            klass = type(obj)
        return self.fget.__get__(obj, klass)()

    def __set__(self, obj, value):
        if not self.fset:
            raise AttributeError("can't set attribute")
        type_ = type(obj)
        return self.fset.__get__(obj, type_)(value)

    def setter(self, func):
        if not isinstance(func, (classmethod, staticmethod)):
            func = classmethod(func)
        self.fset = func
        return self


def classproperty(func):
    '''
    Applies ClassPropertyDescriptor as you would a normal
    @property descriptor
    '''
    if not isinstance(func, (classmethod, staticmethod)):
        func = classmethod(func)

    return ClassPropertyDescriptor(func)
