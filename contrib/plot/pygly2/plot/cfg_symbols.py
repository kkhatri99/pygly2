from functools import partial

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.path import Path
import matplotlib.patches as patches
import matplotlib

from pygly2.structure import Modification
from pygly2.utils.enum import Enum


class ResidueShape(Enum):
    circle = 1
    square = 2
    bisected_square = 3
    triangle = 4
    star = 5
    diamond = 6
    top_bisected_diamond = 7
    left_bisected_diamond = 8
    right_bisected_diamond = 9
    bottom_bisected_diamond = 10


class UnknownShapeException(Exception):
    pass


def residue_shape(monosaccharide):
    if any(mod == Modification.a for p, mod in monosaccharide.modifications.items()):
        return resolve_acid_shape(monosaccharide)
    if "hex" in [monosaccharide.superclass]:
        if any(sub.name == 'n_acetyl' for sub in monosaccharide.substituents()):
            return ResidueShape.square
        elif any(sub.name == 'amino' for sub in monosaccharide.substituents()):
            return ResidueShape.bisected_square
        elif any(mod == Modification.d for p, mod in monosaccharide.modifications.items()):
            return ResidueShape.triangle

        return ResidueShape.circle
    elif "pen" in [monosaccharide.superclass]:
        if 'xyl' in monosaccharide.stem:
            return ResidueShape.star
    else:
        raise UnknownShapeException(monosaccharide)


def resolve_acid_shape(monosaccharide):
    if ('gro' in monosaccharide.stem) and ('gal' in monosaccharide.stem):
        if any(sub.name == 'n_acetyl' for sub in monosaccharide.substituents()):
            return ResidueShape.diamond
        elif any(sub.name == 'n_glycolyl' for sub in monosaccharide.substituents()):
            return ResidueShape.diamond
        else:
            return ResidueShape.diamond
    elif 'glc' in monosaccharide.stem:
        return ResidueShape.top_bisected_diamond
    elif 'gal' in monosaccharide.stem:
        return ResidueShape.left_bisected_diamond
    elif 'man' in monosaccharide.stem:
        return ResidueShape.right_bisected_diamond
    elif 'ido' in monosaccharide.stem:
        return ResidueShape.bottom_bisected_diamond


class ResidueColor(Enum):
    gal = 'yellow'
    glc = 'blue'
    man = 'green'
    fuc = 'red'
    xyl = 'orange'
    neuac = 'purple'
    neugc = 'lightblue'
    kdn = 'green'
    glca = 'blue'
    idoa = 'tan'
    gala = 'yellow'
    mana = 'green'


def residue_color(monosaccharide):
    if any(mod == Modification.a for p, mod in monosaccharide.modifications.items()):
            return resolve_acid_color(monosaccharide)
    if "hex" in [monosaccharide.superclass]:
        if any(mod == Modification.d for p, mod in monosaccharide.modifications.items()):
            return ResidueColor.fuc
    return ResidueColor[monosaccharide.stem[0]]


def resolve_acid_color(monosaccharide):
    if ('gro' in monosaccharide.stem) and ('gal' in monosaccharide.stem):
        if any(sub.name == 'n_acetyl' for sub in monosaccharide.substituents()):
            return ResidueColor.neuac
        elif any(sub.name == 'n_glycolyl' for sub in monosaccharide.substituents()):
            return ResidueColor.neugc
        else:
            return ResidueColor.kdn
    elif 'glc' in monosaccharide.stem:
        return ResidueColor.glca
    elif 'gal' in monosaccharide.stem:
        return ResidueColor.gala
    elif 'man' in monosaccharide.stem:
        return ResidueColor.mana
    elif 'ido' in monosaccharide.stem:
        return ResidueColor.idoa


def get_symbol(monosaccharide):
    col = residue_color(monosaccharide)
    shp = residue_shape(monosaccharide)
    return shp, col


def draw(monosaccharide, x, y, ax, scale=0.1):
    shape, color = get_symbol(monosaccharide)
    drawer = draw_map.get(shape)
    print(shape, draw_square)
    if drawer is None:
        raise Exception("Don't know how to draw {}".format(shape))
    drawer(ax, x, y, color, scale=scale)
draw_map = {}


def draw_circle(ax, x, y, color, scale=0.1):
    path = Path(unit_circle.vertices * scale, unit_circle.codes)
    trans = matplotlib.transforms.Affine2D().translate(x, y)
    t_path = path.transformed(trans)
    patch = patches.PathPatch(t_path, facecolor=color.value, lw=1, zorder=2)
    ax.add_patch(patch)
draw_map[ResidueShape.circle] = draw_circle
unit_circle = Path.unit_circle()


def draw_square(ax, x, y, color, scale=0.1):
    square_verts = np.array([
        (0.5, 0.5),
        (0.5, -0.5),
        (-0.5, -0.5),
        (-0.5, 0.5),
        (0.5, 0.5),
        (0., 0.),
    ]) * 2
    square_codes = [
        Path.MOVETO,
        Path.LINETO,
        Path.LINETO,
        Path.LINETO,
        Path.LINETO,
        Path.CLOSEPOLY,
    ]
    path = Path(square_verts * scale, square_codes)
    trans = matplotlib.transforms.Affine2D().translate(x, y)
    t_path = path.transformed(trans)
    patch = patches.PathPatch(t_path, facecolor=color.value, lw=1, zorder=2)
    ax.add_patch(patch)
draw_map[ResidueShape.square] = draw_square
unit_rectangle = Path.unit_rectangle()


def draw_triangle(ax, x, y, color, scale=0.1):
    path = Path(unit_triangle.vertices * scale, unit_triangle.codes)
    trans = matplotlib.transforms.Affine2D().translate(x, y)
    t_path = path.transformed(trans)
    patch = patches.PathPatch(t_path, facecolor=color.value, lw=1, zorder=2)
    ax.add_patch(patch)
draw_map[ResidueShape.triangle] = draw_triangle
unit_triangle = Path.unit_regular_polygon(3)


def draw_bisected_square(ax, x, y, color, scale=0.1):
    lower_verts = (np.array([
            (0., 0.),
            (1.0, 0),
            (0, 1.0),
            (0, 0),
            (0., 0.),
            ]) - 0.5) / 4

    upper_verts = (np.array([
            (1., 1.),
            (1.0, 0),
            (0, 1.0),
            (1, 1),
            (0., 0.),
            ]) - 0.5) / 4

    codes = [Path.MOVETO,
             Path.LINETO,
             Path.LINETO,
             Path.LINETO,
             Path.CLOSEPOLY,
             ]

    lower_path = Path(lower_verts, codes).transformed(
        matplotlib.transforms.Affine2D().translate(x, y))
    upper_path = Path(upper_verts, codes).transformed(
        matplotlib.transforms.Affine2D().translate(x, y))

    patch = patches.PathPatch(lower_path, facecolor=color.value, lw=1, zorder=2)
    ax.add_patch(patch)
    patch = patches.PathPatch(upper_path, facecolor="white", lw=1, zorder=2)
    ax.add_patch(patch)
draw_map[ResidueShape.bisected_square] = draw_bisected_square


def draw_diamond(ax, x, y, color, scale=0.1):
    path = Path(unit_diamond.vertices * scale, unit_diamond.codes)
    trans = matplotlib.transforms.Affine2D().translate(x, y)
    t_path = path.transformed(trans)
    patch = patches.PathPatch(t_path, facecolor=color.value, lw=1, zorder=2)
    ax.add_patch(patch)
draw_map[ResidueShape.diamond] = draw_diamond
unit_diamond = Path.unit_regular_polygon(4)


def draw_vertical_bisected_diamond(ax, x, y, color, scale=0.1, side=None):
    lower_verts = (np.array([
            (0., 0.),
            (1.0, 0),
            (0, 1.0),
            (0, 0),
            (0., 0.),
            ]) - 0.5) / 5

    upper_verts = (np.array([
            (1., 1.),
            (1.0, 0),
            (0, 1.0),
            (1, 1),
            (0., 0.),
            ]) - 0.5) / 5

    codes = [
        Path.MOVETO,
        Path.LINETO,
        Path.LINETO,
        Path.LINETO,
        Path.CLOSEPOLY,
    ]

    lower_path = Path(lower_verts, codes).transformed(
        matplotlib.transforms.Affine2D().translate(x, y).rotate_deg_around(x, y, 45))
    upper_path = Path(upper_verts, codes).transformed(
        matplotlib.transforms.Affine2D().translate(x, y).rotate_deg_around(x, y, 45))

    if side == 'top':
        top_color = color.value
        bottom_color = 'white'
    elif side == 'bottom':
        top_color = 'white'
        bottom_color = color.value
    patch = patches.PathPatch(lower_path, facecolor=bottom_color, lw=1, zorder=2)
    ax.add_patch(patch)
    patch = patches.PathPatch(upper_path, facecolor=top_color, lw=1, zorder=2)
    ax.add_patch(patch)
draw_map[ResidueShape.top_bisected_diamond] = partial(draw_vertical_bisected_diamond, side='top')
draw_map[ResidueShape.bottom_bisected_diamond] = partial(draw_vertical_bisected_diamond, side='bottom')


def draw_horizontal_bisected_diamond(ax, x, y, color, scale=0.1, side=None):
    left_verts = (np.array([
            (0., 0.),
            (1.0, 0),
            (0, 1.0),
            (0, 0),
            (0., 0.),
            ]) - 0.5) / 5

    right_verts = (np.array([
            (1., 1.),
            (1.0, 0),
            (0, 1.0),
            (1, 1),
            (0., 0.),
            ]) - 0.5) / 5

    codes = [
        Path.MOVETO,
        Path.LINETO,
        Path.LINETO,
        Path.LINETO,
        Path.CLOSEPOLY,
    ]
    if side == 'left':
        left_color = color.value
        right_color = 'white'
    elif side == 'right':
        left_color = 'white'
        right_color = color.value
    left_path = Path(left_verts, codes).transformed(
        matplotlib.transforms.Affine2D().translate(x, y).rotate_deg_around(x, y, -45))
    right_path = Path(right_verts, codes).transformed(
        matplotlib.transforms.Affine2D().translate(x, y).rotate_deg_around(x, y, -45))

    patch = patches.PathPatch(left_path, facecolor=left_color, lw=1, zorder=2)
    ax.add_patch(patch)
    patch = patches.PathPatch(right_path, facecolor=right_color, lw=1, zorder=2)
    ax.add_patch(patch)

draw_map[ResidueShape.right_bisected_diamond] = partial(draw_horizontal_bisected_diamond, side='right')
draw_map[ResidueShape.left_bisected_diamond] = partial(draw_horizontal_bisected_diamond, side='left')


def draw_star(ax, x, y, color, scale=0.1):
    path = Path(unit_star.vertices * scale, unit_star.codes)
    trans = matplotlib.transforms.Affine2D().translate(x, y)
    t_path = path.transformed(trans)
    patch = patches.PathPatch(t_path, facecolor=color.value, lw=1, zorder=2)
    ax.add_patch(patch)
unit_star = Path.unit_regular_star(5, 0.3)
draw_map[ResidueShape.star] = draw_star