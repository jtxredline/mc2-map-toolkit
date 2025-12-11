import bpy
import math, mathutils
import os
import shutil
from bpy_extras.io_utils import axis_conversion

def create_get_collection(col_name):
    found = False
    for c in bpy.data.collections:
        if c.name == col_name:
            found = True
            return c
    if not found:
        c = bpy.data.collections.new(col_name)
        bpy.context.scene.collection.children.link(c)
        return c

def recur_layer_collection(layer_col, col_name):
    found = None
    if (layer_col.name == col_name):
        return layer_col
    for layer in layer_col.children:
        found = recur_layer_collection(layer, col_name)
        if found:
            return found

def set_active_collection(col_name):    
    target_col = recur_layer_collection(bpy.context.view_layer.layer_collection, col_name)
    if target_col:
        bpy.context.view_layer.active_layer_collection = target_col
    else:
        print ('Collection ' + col_name + ' not found')
        return False

def link_col_to_col(col_from, col_to):
    bpy.context.scene.collection.children.unlink(col_from)
    col_to.children.link(col_from)

def select_obj(o):
    o.select_set(True)
    bpy.context.view_layer.objects.active = o

def round_vector3(vector3):
    def round_float(f):
        rounded = round(f, 6)
        return 0.0 if abs(rounded) < 1e-6 else rounded
    x, y, z = vector3
    return (round_float(x), round_float(y), round_float(z))

def translate_vector3(vector3):
    x, y, z = vector3
    return (-x, z, y)

def vector3_to_string(vector3, separator):
    x, y, z = vector3
    return '%.6f' % x + separator + '%.6f' % y + separator + '%.6f' % z

def translate_uv(uv):
    return (uv[0], 1 - uv[1])

def bytes_to_int(bytes) -> int:
    return int.from_bytes(bytes, byteorder='little')

def write_file(filepath, content):
    with open (filepath, 'w') as file:
        for l in content:
            file.write("%s" % l)

def calc_emin_emax(col_inst):
    # Calculate extents bounding box of a collection instance,
    # returns emin = upper left bottom corner, emax = lower right top corner,
    # assuming blender orientation x - left, y - bottom, z - top.

    inst = bpy.context.active_object
    verts = []
    depsgraph = bpy.context.evaluated_depsgraph_get() # Can this be reused?

    for obj in col_inst.instance_collection.all_objects:
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        verts.extend([eval_obj.matrix_world @ v.co for v in mesh.vertices])
        eval_obj.to_mesh_clear() # ?

    verts_world = ([col_inst.matrix_world @ v for v in verts])
    try:
        min_corner = mathutils.Vector((min(p[i] for p in verts_world) for i in range(3)))
        max_corner = mathutils.Vector((max(p[i] for p in verts_world) for i in range(3)))

        emin = translate_vector3((max_corner.x, min_corner.y, min_corner.z))
        emax = translate_vector3((min_corner.x, max_corner.y, max_corner.z))

        return emin, emax

    except:
        print(col_inst.name)
        return (0, 0, 0), (0, 0, 0) # Janky shi

def to_matrix34(matrix): # convert_to_matrix34?
    matrix = matrix.copy()

    # Convert coordinate space
    mat_rot = mathutils.Matrix.Rotation(math.radians(-180.0), 4, 'Y') @ mathutils.Matrix.Rotation(math.radians(-90.0), 4, 'X')
    matrix @= mat_rot

    mtx_convert = axis_conversion(from_forward='-Y', 
        from_up='Z',
        to_forward='-Z',
        to_up='Y').to_4x4()
    matrix = mtx_convert @ matrix
    # Shuffle elements into correct spots here?
    return matrix

def get_last_dir():
    parent_dir = os.path.dirname(__file__)
    globals_path = os.path.join(parent_dir, 'globals.py')
    last_dir = ''

    if os.path.exists(globals_path):
        with open(globals_path, 'r') as file:
            lines = file.read().splitlines()
            for l_idx, l in enumerate(lines):
                 if l.startswith('mc2_dir'):
                     last_dir = l.rsplit("=")[1].strip()[1:-1]
                     return last_dir
    else: return ''

def get_last_map_name():
    parent_dir = os.path.dirname(__file__)
    globals_path = os.path.join(parent_dir, 'globals.py')
    map_name = ''

    if os.path.exists(globals_path):
        with open(globals_path, 'r') as file:
            lines = file.read().splitlines()
            for l_idx, l in enumerate(lines):
                 if l.startswith('map_name'):
                     map_name = l.rsplit("=")[1].strip()[1:-1]
                     return map_name
    else: return ''

def validate_mc2_dir(path: str) -> (bool, str):
    if not path:
        return False, 'No path set'
    if not os.path.isdir(path):
        return False, 'Directory does not exist'

    unique_folders = ['anim', 'bound', 'fonts', 'geometry', 'model', 'tune'] # Folders unique to assets_p
    for f in unique_folders:
        if f not in os.listdir(path):
            return False, 'Assets not extracted'
    return True, ''

def make_backup(fp):
    dir, file = os.path.split(fp)
    backup_dest = os.path.join(dir, 'backup')
    backup_file_dest = os.path.join(backup_dest, file)

    if not os.path.exists(backup_file_dest): # Don't create a backup if it already exists
        # Create directory if it doesn't exist yet
        if not os.path.exists(backup_dest):
            os.makedirs(backup_dest)
        
        shutil.copyfile(fp, backup_file_dest)

def load_texture_from_path(file_path):
    from .tex_file import TEXFile
    
    # extract the filename for manual image format names
    image_name= os.path.splitext(os.path.basename(file_path))[0]   
    if file_path.lower().endswith(".tex"):
        tf = TEXFile(file_path)
        if tf.is_valid():
            if tf.is_compressed_format():
                tf.decompress()
            tf_img = tf.to_blender_image(image_name)
            tf_img.filepath_raw = file_path # set filepath manually for TEX stuff, since it didn't come from an actual file import
            tf_img.alpha_mode = 'CHANNEL_PACKED' # Doesn't always work, especially for letter decal meshes
            return tf_img
        else:
            print("Invalid TEX file: " + file_path)
    else:
        img = bpy.data.images.load(file_path)
        return img
        
    return None

def image_load_placeholder(name, path):
    image = bpy.data.images.new(name, 128, 128)
    image.filepath_raw = path
    return image
        
def try_load_texture(tex_name, search_path):
    existing_image = bpy.data.images.get(tex_name)
    if existing_image is not None:
        return existing_image

    bl_img = None
    fp = os.path.join(search_path, tex_name + ".tex")
    if os.path.exists(fp):
        try:
            bl_img = load_texture_from_path(fp)
        except:
            print('Tex file load failed, creating placeholder: ' + tex_name)
            bl_img = image_load_placeholder(tex_name, fp)

    # if bl_img is None:
    #     standard_extensions = (".tga", ".bmp", ".png")
    #     for ext in standard_extensions:
    #         fp = os.path.join(search_path, tex_name + ext)
    #         if os.path.exists(fp):
    #             bl_img = load_texture_from_path(fp)
    #             if bl_img is not None:
    #                 break

    # if bl_img is None:
    #     bl_img = image_load_placeholder(tex_name, os.path.join(search_path, tex_name))
    return bl_img