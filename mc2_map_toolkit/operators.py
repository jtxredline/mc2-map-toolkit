import bpy
import os
import shutil
import math, mathutils
from bpy_extras.io_utils import axis_conversion
from .utils import create_get_collection, link_col_to_col, set_active_collection, calc_emin_emax, to_matrix34, write_file, make_backup, round_vector3, translate_vector3, vector3_to_string
from .import_xmod import import_xmod

class MC2_OT_SetupScene(bpy.types.Operator):
    bl_idname = "mc2.setup_scene"
    bl_label = "Setup Scene"
    bl_options = {'REGISTER', 'UNDO'}

    # @classmethod
    # def poll(cls, context):
    #     props = getattr(context.scene, "mc2_props", None)
    #     if not props:
    #         return False
    #     valid, _ = validate_mc2_dir(props.mc2_dir)
    #     return valid

    @classmethod
    def poll(cls, context):
        map_name = context.scene.mc2_props.map_name
        if map_name in bpy.data.collections:
            return False
        return True

    def execute(self, context):
        # scene = bpy.context.scene
        # bpy.data.scenes.new("Scene")
        # bpy.data.scenes.remove(scene, do_unlink=True)

        map_name = context.scene.mc2_props.map_name
        city_col = create_get_collection(map_name)

        city_source_col = create_get_collection(map_name + '_source')
        link_col_to_col(city_source_col, city_col)
        #city_source_col.hide_viewport = True
        #city_source_col.hide_render = True

        city_hoods_col = create_get_collection(map_name + '_hoods')
        link_col_to_col(city_hoods_col, city_col)

        prop_templates_col = create_get_collection(map_name + '_prop_templates')
        link_col_to_col(prop_templates_col, city_source_col)

        city_models_col = create_get_collection(map_name + '_city_models')
        link_col_to_col(city_models_col, city_source_col)

        city_prop_col = create_get_collection(map_name + '.prop') # Parent prop collection
        link_col_to_col(city_prop_col, city_col)

        city_props = create_get_collection(map_name + '_props') # Regular props collection (hitable/movable)
        link_col_to_col(city_props, city_prop_col)

        city_props_fixed = create_get_collection(map_name + '_props_fixed') # Fixed props collection (immovable)
        link_col_to_col(city_props_fixed, city_prop_col)

        city_props_gfx = create_get_collection(map_name + '_props_gfx') # Visual-only props collection
        link_col_to_col(city_props_gfx, city_prop_col)

        # Setup camera settings
        context.space_data.lens = 70
        context.space_data.clip_start = 1
        context.space_data.clip_end = 15000
        context.space_data.shading.color_type = 'TEXTURE'

        return {'FINISHED'}

class MC2_OT_ClearScene(bpy.types.Operator):
    bl_idname = "mc2.clear_scene"
    bl_label = "Clear Scene"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        map_name = context.scene.mc2_props.map_name
        for col in bpy.data.collections:
            if col.name.startswith(map_name):
                return True
        return False

    def execute(self, context):
        # TODO: Find a faster way for this
        map_name = context.scene.mc2_props.map_name
        col = bpy.data.collections.get(map_name)

        for col in bpy.data.collections:
            if col.name.startswith(map_name):
                objs = [o for o in col.objects if o.users == 1]
                while objs:
                    bpy.data.objects.remove(objs.pop())
                bpy.data.collections.remove(col)
                
        # Clean up unused data blocks
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        
        self.report({'INFO'}, "Scene cleared")

        return {'FINISHED'}

class MC2_OT_RestoreBackup(bpy.types.Operator):
    bl_idname = "mc2.restore_backup"
    bl_label = "Restore Backup"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        mc2_dir = context.scene.mc2_props.mc2_dir
        map_name = context.scene.mc2_props.map_name
        city_backup_path = os.path.join(mc2_dir, 'city', map_name, 'backup')

        if os.path.exists(city_backup_path):
            return True
        return False

    def execute(self, context):
        mc2_dir = context.scene.mc2_props.mc2_dir
        map_name = context.scene.mc2_props.map_name
        city_path = os.path.join(mc2_dir, 'city', map_name)
        city_backup_path = os.path.join(city_path, 'backup')

        for backup in os.listdir(city_backup_path):
            backup_path = os.path.join(city_backup_path, backup)
            file_path = os.path.join(city_path, backup)
            shutil.copyfile(backup_path, file_path)

        self.report({'INFO'}, "Restored backup")
        return {'FINISHED'}

class MC2_OT_ImportCityModels(bpy.types.Operator):
    bl_idname = "mc2.import_city_models"
    bl_label = "Import City Models"
    #bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        #self.report({'INFO'}, "Importing city models...")
    
        mc2_dir = context.scene.mc2_props.mc2_dir
        map_name = context.scene.mc2_props.map_name
        city_path = os.path.join(mc2_dir, 'city', map_name)
        city_models_path = os.path.join(city_path, 'models')

        # Get collections
        city_models_col = create_get_collection(map_name + '_city_models')

        # Parse .cc files
        max_cc_search = 4

        for file in os.listdir(city_models_path):
            if file.endswith('.cc'):
                cc_path = os.path.join(city_models_path, file)
                basename = file.rsplit('.')[0]

                # Create model collection and set it as active
                model_col = create_get_collection(basename) # (basename.rsplit('#')[0])
                link_col_to_col(model_col, city_models_col)
                set_active_collection(model_col.name)
                
                with open(cc_path, 'r') as f:
                    lines = f.readlines()
                    
                    num_inst_cpv = int(lines[0].split()[1])
                    bounding_sphere = [eval(s) for s in lines[1].split()[1:]]
                    
                    # Parse model extensions and format names            
                    names = []            
                    islod1 = False
                    
                    for i, line in enumerate(lines):
                        if line.startswith('lod 0'):      
                            # Check if LOD0s exist, if not, skip to LOD1 as the highest detail model
                            if lines[i + 1].startswith('}'):
                                islod1 = True
                                break
                            
                            for j in range(1, max_cc_search):
                                if not lines[i + j].startswith('}'):
                                    ext = lines[i + j].strip()
                                    names.append(basename + '_0_' + ext + '.xmod')
                                else: break
                        
                        if line.startswith('lod 1') and islod1:
                            for j in range(1, max_cc_search):
                                if not lines[i + j].startswith('}'):
                                    ext = lines[i + j].strip()
                                    names.append(basename + '_1_' + ext + '.xmod')
                                else: break
                    
                    # Import models
                    for name in names:
                        fp = os.path.join(city_models_path, name)
                        if os.path.exists(fp):
                            if num_inst_cpv > 0:
                                model = import_xmod(fp, has_xbcpv = True)
                            elif num_inst_cpv == 0:
                                model = import_xmod(fp, has_xbcpv = False)
                            
                        else: print(fp + ' does not exist.')
        
        self.report({'INFO'}, f"Imported {map_name} city models")
        return {'FINISHED'}

# Might not need this
class PropDef:
    def __init__(self):
        self.name = None
        self.numlods = 0
        self.lods = None # List of LOD levels (0, 2), etc.
        self.sphere = None
        # self.numlights = 0
        # self.lights
        # Prop template stuff
        self.animation = None
        self.numparts = 0
        self.parts = [] # List of dictionaries (name/offset)
        self.fixedobject = 0
        self.obstacle = 0
        self.gfxonly = 0
        self.drivable = 0
        self.far = 0

class MC2_OT_ImportProps_Old(bpy.types.Operator):
    bl_idname = "mc2.import_props_old"
    bl_label = "Import Props Old"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mc2_dir = context.scene.mc2_props.mc2_dir
        map_name = context.scene.mc2_props.map_name
        city_path = os.path.join(mc2_dir, 'city', map_name)
        city_models_path = os.path.join(city_path, 'models')

        # Get collections
        prop_templates_col = create_get_collection(map_name + '_prop_templates')
        set_active_collection(prop_templates_col.name)

        # Parse .pdef files
        pdefs = []
        for file in os.listdir(city_path):
            if file.endswith('.pdef'):
                basename = file.rsplit('.')[0]
                pdef = PropDef()
                pdef.name = basename.lower()

                pdef_fp = os.path.join(city_path, file)
                with open(pdef_fp, 'r') as file:                
                    lines = file.read().splitlines()
                    for l in lines:
                        if l.startswith('lods:'):
                            tok = l.split()
                            pdef.numlods = int(tok[1])
                            pdef.lods = tok[-pdef.numlods:] # [0, 2], etc
                        if l.startswith('sphere:'):
                            tok = l.split()
                            pdef.sphere = (float(tok[1]), float(tok[2]), float(tok[3]), float(tok[4]))
                        # TODO: Parse lightdata here
                pdefs.append(pdef)
        
        # Parse .prop file
        num_prop_types = 0

        city_props_fp = os.path.join(city_path, map_name + '.prop')
        if os.path.exists(city_props_fp):
            with open(city_props_fp, 'r') as file:
                lines = file.read().splitlines()

                #prop_count = int(lines[0].split()[1])
                #fixed_prop_count = int(lines[1].split()[1])
                #gfx_prop_count = int(lines[2].split()[1])
                num_prop_types = int(lines[3].split()[1])

                prop_type_ctr = 1

                # Parse prop templates
                for l_idx, l in enumerate(lines):
                    if prop_type_ctr <= num_prop_types:
                        if l.startswith('prop_template '):
                            prop_idx = num_prop_types - prop_type_ctr # Reverse idx
                            prop_template_name = l.split()[1].lower()

                            if prop_template_name != pdefs[prop_idx].name:
                                # TODO: Create safer name matching, it's not always in reverse-alphabetical order! See paris.prop
                                print('Prop pdef mismatch:', prop_template_name, pdefs[prop_idx].name)
                                break
                            
                            # Read prop template block                        
                            for i in range(64): # Max amount of lines for a prop template
                                idx = l_idx + i
                                line_tok = lines[idx].split()

                                if line_tok[0] == '}': break # # If closing bracket is found, stop the loop
                                if line_tok[0].startswith('animation:'): pdefs[prop_idx].animation = int(line_tok[1])

                                if line_tok[0].startswith('numparts:'):
                                    numparts = int(line_tok[1])
                                    pdefs[prop_idx].numparts = numparts
                                    for i in range(0, numparts * 4, 4):
                                        name = lines[idx + i + 2].split()[1].lower()
                                        offset = lines[idx + i + 3].split()[1:]
                                        offset = [float(x) for x in offset]
                                        pdefs[prop_idx].parts.append([name, offset]) # Use dict instead? {name: offset}

                                if line_tok[0].startswith('FixedObject:'): pdefs[prop_idx].fixedobject = int(line_tok[1])
                                if line_tok[0].startswith('Obstacle:'): pdefs[prop_idx].obstacle = int(line_tok[1])
                                if line_tok[0].startswith('GfxOnly:'): pdefs[prop_idx].gfxonly = int(line_tok[1])
                                if line_tok[0].startswith('Drivable:'): pdefs[prop_idx].drivable = int(line_tok[1])
                                if line_tok[0].startswith('Far:'): pdefs[prop_idx].far = int(line_tok[1])
                            
                            prop_type_ctr += 1
                    else: break
                
                # Import props using pdef and prop template data
                prop_ext = '_0.xmod' # Highest LOD extension
                for pdef in pdefs:
                    prop_col = create_get_collection(pdef.name)
                    link_col_to_col(prop_col, prop_templates_col)
                    set_active_collection(prop_col.name)

                    prop_fp = os.path.join(city_models_path, pdef.name + prop_ext)

                    # Try-excepts below are because TEX importing seems to fail on some textures, resolve later.
                    # l_prop_breakglass_04x_glass_0, p_prop_ferris_box_x_0, etc. -> Don't seem to exist?

                    if os.path.exists(prop_fp):
                        try:
                            import_xmod(prop_fp)
                        except:
                            print('Could not import prop model, creating empty:', pdef.name)
                            prop_empty = bpy.data.objects.new(pdef.name, None)
                            prop_col.objects.link(prop_empty)
                    
                    # Import parts from the prop template
                    for part in pdef.parts:
                        if part[0] == pdef.name + '_glass': # Try importing glass props
                            prop_glass_fp = os.path.join(city_models_path, pdef.name + '_glass' + prop_ext)
                            if os.path.exists(prop_glass_fp):
                                try:
                                    part_obj = import_xmod(prop_glass_fp)
                                except:
                                    print('Could not import glass model, creating empty:', part[0])
                                    part_obj = bpy.data.objects.new(part[0], None)
                                    prop_col.objects.link(part_obj)
                            else:
                                part_obj = bpy.data.objects.new(part[0], None)
                                prop_col.objects.link(part_obj)
                        else:
                            part_obj = bpy.data.objects.new(part[0], None)
                            prop_col.objects.link(part_obj)
                        
                        # TODO: Add offset to part_obj
        
        self.report({'INFO'}, f"Imported {map_name} props")
        return {'FINISHED'}

class MC2_OT_ImportProps(bpy.types.Operator):
    bl_idname = "mc2.import_props"
    bl_label = "Import Props"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):

        os.system('cls') ### TEMP ###

        mc2_dir = context.scene.mc2_props.mc2_dir
        map_name = context.scene.mc2_props.map_name
        city_path = os.path.join(mc2_dir, 'city', map_name)
        city_models_path = os.path.join(city_path, 'models')

        # Get collections
        prop_templates_col = create_get_collection(map_name + '_prop_templates')
        set_active_collection(prop_templates_col.name)

        # Don't need to parse pdefs for now
        # # Parse .pdef files
        # pdefs = []
        # for file in os.listdir(city_path):
        #     if file.endswith('.pdef'):
        #         name = file.rsplit('.')[0]

        #         pdef_fp = os.path.join(city_path, file)
        #         with open(pdef_fp, 'r') as file:                
        #             lines = file.read().splitlines()
        #             for l in lines:

        # Parse .prop file
        num_prop_types = 0

        city_props_fp = os.path.join(city_path, map_name + '.prop')
        if os.path.exists(city_props_fp):
            with open(city_props_fp, 'r') as file:
                lines = file.read().splitlines()

                #prop_count = int(lines[0].split()[1])
                #fixed_prop_count = int(lines[1].split()[1])
                #gfx_prop_count = int(lines[2].split()[1])
                num_prop_types = int(lines[3].split()[1])

                # Parse prop templates
                prop_type_ctr = 1

                for l_idx, l in enumerate(lines):
                    if prop_type_ctr <= num_prop_types:
                        if l.startswith('prop_template '):
                            prop_template_name = l.split()[1].lower()

                            animation = 0
                            numparts = 0
                            fixedobject = 0
                            obstacle = 0
                            gfxonly = 0
                            drivable = 0
                            far = 0
                            parts = []

                            pdef_fp = os.path.join(city_path, prop_template_name + '.pdef')
                            if not os.path.exists(pdef_fp):
                                print('Prop pdef missing:', prop_template_name)
                                break
                            
                            # Read prop template block
                            for i in range(64): # Max amount of lines for a prop template
                                t_idx = l_idx + i
                                line_tok = lines[t_idx].split()

                                if line_tok[0] == '}': break # If closing bracket is found, stop the loop
                                if line_tok[0].startswith('animation'): animation = int(line_tok[1])
                                if line_tok[0].startswith('numparts'):
                                    numparts = int(line_tok[1])
                                    for i in range(0, numparts * 4, 4):
                                        name = lines[t_idx + i + 2].split()[1].lower()
                                        offset = lines[t_idx + i + 3].split()[1:]
                                        offset = [float(x) for x in offset]
                                        parts.append([name, offset])
                                
                                if line_tok[0].startswith('FixedObject:'): fixedobject = int(line_tok[1])
                                if line_tok[0].startswith('Obstacle:'): obstacle = int(line_tok[1])
                                if line_tok[0].startswith('GfxOnly:'): gfxonly = int(line_tok[1])
                                if line_tok[0].startswith('Drivable:'): drivable = int(line_tok[1])
                                if line_tok[0].startswith('Far:'): far = int(line_tok[1])
                            
                            prop_type_ctr += 1
                                                    
                            # Import prop
                            lod_ext = '_0.xmod' # Highest LOD extension
                            prop_col = create_get_collection(prop_template_name)
                            link_col_to_col(prop_col, prop_templates_col)
                            set_active_collection(prop_col.name)

                            prop_fp = os.path.join(city_models_path, prop_template_name + lod_ext)

                            # Try-excepts below are because TEX importing seems to fail on some textures, resolve later.
                            # l_prop_breakglass_04x_glass_0, p_prop_ferris_box_x_0, etc. -> Don't seem to exist?

                            if os.path.exists(prop_fp):
                                prop = None
                                try:
                                    prop = import_xmod(prop_fp)
                                except:
                                    print('Prop was found but could not import, creating empty:', prop_template_name)
                                    prop = bpy.data.objects.new(prop_template_name, None)
                                    prop_col.objects.link(prop)
                                
                                # Assign template variables as custom properties
                                prop['animation'] = animation
                                prop['fixedobject'] = fixedobject
                                prop['obstacle'] = obstacle
                                prop['gfxonly'] = gfxonly
                                prop['drivable'] = drivable
                                prop['far'] = far

                            else:
                                print('Prop xmod was not found:', prop_template_name + lod_ext)

                            # Import prop parts
                            for part in parts:
                                part_fp = os.path.join(city_models_path, part[0] + lod_ext)
                                if os.path.exists(part_fp):
                                    part_xmod = import_xmod(part_fp)
                                    part_xmod.name = part[0]
                                    part_xmod.location = translate_vector3(part[1])

                                    if 'particle' or 'breakpart' in part[0]: # Hide particles and breakparts
                                        part_xmod.hide_viewport = True
                                        part_xmod.hide_render = True
                                else:
                                    part_empty = bpy.data.objects.new(part[0], None) # Add part as empty if xmod was not found
                                    prop_col.objects.link(part_empty)
                                    part_empty.location = translate_vector3(part[1])

                    else: break

        #Try to contain needed info directly in the prop collections, custom properties etc. straight away, instead of messing with PropDef

        self.report({'INFO'}, f"Imported {map_name} props")
        return {'FINISHED'}

class MC2_OT_SpawnCityModels(bpy.types.Operator):
    bl_idname = "mc2.spawn_city_models"
    bl_label = "Spawn City Models"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mc2_dir = context.scene.mc2_props.mc2_dir
        map_name = context.scene.mc2_props.map_name
        city_path = os.path.join(mc2_dir, 'city', map_name)

        # Get collections
        city_models_col = create_get_collection(map_name + '_city_models')
        city_hoods_col = create_get_collection(map_name + '_hoods')

        # Read lvl file
        lvl_fp = os.path.join(city_path, map_name + '.lvl')
        if os.path.exists(lvl_fp):
            hoods = []
            uniques = {}

            # Temp object to be copied to not have to use bpy too much
            bpy.ops.object.collection_instance_add(collection=city_models_col.children[0].name)
            temp_obj = bpy.context.object
            temp_obj.name = 'temp_obj'

            with open(lvl_fp, 'r') as file:
                lines = file.read().splitlines()
                numhoods = int(lines[0].split()[1])

                fails = 0

                for l_idx, l in enumerate(lines):
                    if l.startswith('extents_min '):
                        extents_min = [float(x) for x in lines[l_idx+1].split()]
                    if l.startswith('extents_max '):
                        extents_max = [float(x) for x in lines[l_idx+1].split()]
                    if l.startswith('hood '):
                        hoods.append(lines[l_idx+1].split()[1])
                
                # Read hood file(s)
                for hood in hoods:
                    hood_fp = os.path.join(city_path, hood + '.hood')
                    if os.path.exists(hood_fp):
                        # Set up hood collection
                        hood_col = create_get_collection(hood)
                        link_col_to_col(hood_col, city_hoods_col)

                        hood_unique_col = create_get_collection(hood + '_unique')
                        link_col_to_col(hood_unique_col, hood_col)

                        hood_inst_col = create_get_collection(hood + '_inst')
                        link_col_to_col(hood_inst_col, hood_col)
                        
                        with open(hood_fp, 'r') as file:
                            lines = file.read().splitlines()

                            num_unique_components = lines[1].split()[1]
                            num_instance_components = lines[2].split()[1]

                            for l_idx, l in enumerate(lines):
                                # Spawn unique models
                                if l.startswith('unique_component '):
                                    name = lines[l_idx+1].split()[1].lower() #.rsplit('#')[0]
                                    emin = [float(x) for x in lines[l_idx+2].split()[1:]]
                                    emax = [float(x) for x in lines[l_idx+3].split()[1:]]
                                    
                                    # Spawn collection instance using temp object
                                    model = temp_obj.copy()
                                    hood_unique_col.objects.link(model)
                                    model.instance_collection = bpy.data.collections[name]
                                    model.name = name
                                    uniques[name] = model
                                
                                # Spawn inst models
                                if l.startswith('instance_component '):
                                    inst_type = lines[l_idx+1].split()[1].lower()
                                    owner = lines[l_idx+2].split()[1].lower()
                                    extension = lines[l_idx+3].split()[1]

                                    # TODO: Put this in a function?
                                    # Read Matrix34
                                    row1 = [float(x) for x in lines[l_idx+4].split()]
                                    row2 = [float(x) for x in lines[l_idx+5].split()]
                                    row3 = [float(x) for x in lines[l_idx+6].split()]
                                    translation = [float(x) for x in lines[l_idx+7].split()]

                                    col1 = [row1[0], row2[0], row3[0], translation[0]]
                                    col2 = [row1[1], row2[1], row3[1], translation[1]]
                                    col3 = [row1[2], row2[2], row3[2], translation[2]]

                                    mtx = mathutils.Matrix((col1, col2, col3)).to_4x4()

                                    mtx_convert = axis_conversion(from_forward='-Z',
                                                                    from_up='Y',
                                                                    to_forward='-Y',
                                                                    to_up='Z').to_4x4()
                                    
                                    mtx = mtx_convert @ mtx
                                    mat_rot = mathutils.Matrix.Rotation(math.radians(90), 4, 'X') @ mathutils.Matrix.Rotation(math.radians(180), 4, 'Y')
                                    mtx @= mat_rot
                                    mtx.to_4x4()

                                    emin = [float(x) for x in lines[l_idx+8].split()[1:]]
                                    emax = [float(x) for x in lines[l_idx+9].split()[1:]]

                                    # Spawn collection instance using temp object
                                    model = temp_obj.copy()
                                    hood_inst_col.objects.link(model)
                                    model.instance_collection = bpy.data.collections[inst_type]
                                    model.name = inst_type + '.' + extension
                                    model.matrix_world = mtx

                                    #model.parent = uniques[owner + '#geom'] # fails on l_santamonica_int_02x#geom ? Doesn't seem to exist

                                    # TODO: Figure out / fix parenting, some parent / owner names don't seem to exist
                                    # try:
                                    #     model.parent = uniques[owner + '#geom']
                                    #     print('Owner:', owner, 'Child:', model.name, 'SUCCESS')

                                    # except Exception as e:
                                    #     #print(e)
                                    #     fails += 1
                                    #     print('Owner:', owner, 'Child:', model.name, 'FAILED')

                                    # Add owner and extensions as custom properties for now
                                    model['owner'] = owner
                                    model['extension'] = extension

            # Remove temp obj
            bpy.data.objects.remove(temp_obj)
            print('FAILS:', fails)

        self.report({'INFO'}, f"Spawned {map_name} city models")
        return {'FINISHED'}

class MC2_OT_SpawnProps(bpy.types.Operator):
    bl_idname = "mc2.spawn_props"
    bl_label = "Spawn Props"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mc2_dir = context.scene.mc2_props.mc2_dir
        map_name = context.scene.mc2_props.map_name
        city_path = os.path.join(mc2_dir, 'city', map_name)

        # Get collections
        prop_templates_col = create_get_collection(map_name + '_prop_templates')
        props_col = create_get_collection(map_name + '_props')
        props_fixed_col = create_get_collection(map_name + '_props_fixed')
        props_gfx_col = create_get_collection(map_name + '_props_gfx')

        # Read prop file
        city_props_fp = os.path.join(city_path, map_name + '.prop')
        if os.path.exists(city_props_fp):
            # Temp object to be copied to not have to use bpy too much
            bpy.ops.object.collection_instance_add(collection=prop_templates_col.children[0].name)
            temp_obj = bpy.context.object

            with open(city_props_fp, 'r') as file:
                lines = file.read().splitlines()            

                prop_count = int(lines[0].split()[1])
                prop_fixed_count = int(lines[1].split()[1])
                prop_gfx_count = int(lines[2].split()[1])

                prop_ctr = 0
                prop_fixed_ctr = 0
                prop_gfx_ctr = 0

                for l_idx, l in enumerate(lines):
                    if l.startswith('prop '):
                        prop_id = l.split()[1]
                        if lines[l_idx+1].startswith('\tmatrix {'):
                            # Read Matrix34
                            row1 = [float(x) for x in lines[l_idx+2].split()]
                            row2 = [float(x) for x in lines[l_idx+3].split()]
                            row3 = [float(x) for x in lines[l_idx+4].split()]
                            translation = [float(x) for x in lines[l_idx+5].split()]

                            col1 = [row1[0], row2[0], row3[0], translation[0]]
                            col2 = [row1[1], row2[1], row3[1], translation[1]]
                            col3 = [row1[2], row2[2], row3[2], translation[2]]

                            mtx = mathutils.Matrix((col1, col2, col3)).to_4x4()

                            mtx_convert = axis_conversion(from_forward='-Z',
                                                            from_up='Y',
                                                            to_forward='-Y',
                                                            to_up='Z').to_4x4()
                            
                            mtx = mtx_convert @ mtx
                            mat_rot = mathutils.Matrix.Rotation(math.radians(90), 4, 'X') @ mathutils.Matrix.Rotation(math.radians(180), 4, 'Y')
                            mtx @= mat_rot
                            mtx.to_4x4()

                        if lines[l_idx+7].startswith('\tprop_template:'):
                            prop_name = lines[l_idx+7].split()[1].lower()

                            # Spawn collection instance using temp object
                            prop = temp_obj.copy()

                            # Add it to appropriate collection (prop/fixed/gfx) using the ctr variables
                            if prop_ctr < prop_count:
                                props_col.objects.link(prop)
                                prop_ctr += 1
                            elif prop_fixed_ctr < prop_fixed_count:
                                props_fixed_col.objects.link(prop)
                                prop_fixed_ctr += 1
                            elif prop_gfx_ctr < prop_gfx_count:
                                props_gfx_col.objects.link(prop)
                                prop_gfx_ctr += 1

                            prop.instance_collection = bpy.data.collections[prop_name]
                            prop.name = prop_name + '.' + prop_id
                            prop.matrix_world = mtx
                    
            # Remove temp obj
            bpy.data.objects.remove(temp_obj)
        
        # Disable source collection at the end, needs a better spot
        city_source_col = create_get_collection(map_name + '_source')
        city_source_col.hide_viewport = True
        city_source_col.hide_render = True

        self.report({'INFO'}, f"Spawned {map_name} props")
        return {'FINISHED'}

class MC2_OT_ExportHoods(bpy.types.Operator):
    bl_idname = "mc2.export_hoods"
    bl_label = "Export Hoods"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mc2_dir = context.scene.mc2_props.mc2_dir
        map_name = context.scene.mc2_props.map_name
        city_path = os.path.join(mc2_dir, 'city', map_name)

        # Get collections
        city_hoods_col = create_get_collection(map_name + '_hoods')

        n = '\n'
        t = '\t'
        e = '}' + n
        
        for hood in city_hoods_col.children:
            lines = []
            
            # bpy.data.collections[''] ?, so that they don't get created if they don't exist?
            hood_unique_col = create_get_collection(hood.name + '_unique')
            hood_inst_col = create_get_collection(hood.name + '_inst')

            # Write header
            name = 'name: ' + hood.name + n
            num_unique_components = 'num_unique_components: ' + str(len(hood_unique_col.objects)) + n
            num_instance_components = 'num_instance_components: ' + str(len(hood_inst_col.objects)) + n

            lines.append(name)
            lines.append(num_unique_components)
            lines.append(num_instance_components)
            
            # Write unique components
            ctr = 0 # Ctr as an extension might be dangerous
            for unique in hood_unique_col.all_objects:
                title = 'unique_component ' + str(ctr) + ' {' + n
                name = t + 'name: ' + unique.name + n
                
                emin, emax = calc_emin_emax(unique)
                emin = t + 'emin ' + ('%.6f %.6f %.6f' % emin[:]) + n # TODO: Better way to print a Vector?
                emax = t + 'emax ' + ('%.6f %.6f %.6f' % emax[:]) + n + e
                
                lines.append(title)
                lines.append(name)
                lines.append(emin)
                lines.append(emax)
                ctr += 1
            
            # Write instance components
            ctr = 0
            for inst in hood_inst_col.all_objects:
                title = 'instance_component ' + str(ctr) + ' {' + n
                type, ext = inst.name.rsplit('.')
                type = t + 'type: ' + type + n
                owner = t + 'owner: ' + inst['owner'] + n #'TEST_OWNER' + n # Read owner from a custom property for now
                extension = t + 'extension: ' + ext + n #str(ctr) + n # extension + n

                # Convert world matrix to Matrix34
                matrix = to_matrix34(inst.matrix_world)

                row1 = (matrix[0][0], matrix[1][0], matrix[2][0])
                row2 = (matrix[0][1], matrix[1][1], matrix[2][1])
                row3 = (matrix[0][2], matrix[1][2], matrix[2][2])
                row4 = (matrix[0][3], matrix[1][3], matrix[2][3])

                row1 = t + vector3_to_string(round_vector3(row1), '\t') + n
                row2 = t + vector3_to_string(round_vector3(row2), '\t') + n
                row3 = t + vector3_to_string(round_vector3(row3), '\t') + n
                row4 = t + vector3_to_string(round_vector3(row4), '\t') + n

                emin, emax = calc_emin_emax(inst)
                emin = t + 'emin ' + vector3_to_string(round_vector3(emin), ' ') + n
                emax = t + 'emax ' + vector3_to_string(round_vector3(emax), ' ')+ n + e

                lines.append(title)
                lines.append(type)
                lines.append(owner)
                lines.append(extension)

                lines.append(row1)
                lines.append(row2)
                lines.append(row3)
                lines.append(row4)

                lines.append(emin)
                lines.append(emax)
                ctr += 1

            fp = os.path.join(city_path, hood.name + '.hood')
            make_backup(fp)
            write_file(fp, lines)

        self.report({'INFO'}, f"Exported {map_name} hoods")
        return {'FINISHED'}

class MC2_OT_ExportProps(bpy.types.Operator):
    bl_idname = "mc2.export_props"
    bl_label = "Export Props"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mc2_dir = context.scene.mc2_props.mc2_dir
        map_name = context.scene.mc2_props.map_name
        city_path = os.path.join(mc2_dir, 'city', map_name)

        # Get collections
        prop_templates_col = create_get_collection(map_name + '_prop_templates')
        props_col = create_get_collection(map_name + '_props')
        props_fixed_col = create_get_collection(map_name + '_props_fixed')
        props_gfx_col = create_get_collection(map_name + '_props_gfx')

        n = '\n'
        t = '\t'
        e = '}' + n

        lines = []

        # Write header
        prop_count = 'prop_count: ' + str(len(props_col.objects)) + n
        fixed_prop_count = 'fixed_prop_count: ' + str(len(props_fixed_col.objects)) + n
        gfx_prop_count = 'gfx_prop_count: ' + str(len(props_gfx_col.objects)) + n
        num_prop_types = 'num_prop_types: ' + str(len(prop_templates_col.children)) + n

        lines.append(prop_count)
        lines.append(fixed_prop_count)
        lines.append(gfx_prop_count)
        lines.append(num_prop_types)

        # Write prop templates
        for template in prop_templates_col.children:
            prop_template = 'prop_template ' + template.name + ' {' + n
            # Defaults
            animation = t + 'animation: 0' + n
            parts = ''
            fixedobject = t + 'FixedObject: 0' + n
            obstacle = t + 'Obstacle: 0' + n
            gfxonly = t + 'GfxOnly: 0' + n
            drivable = t + 'Drivable: 0' + n
            far = t + 'Far: 0' + n + e

            part_ctr = 0
            objs = template.objects
            for o in objs:
                part = ''
                if not o.hide_viewport: # TODO: Probably need a more reliable way to distinguish the actual prop from its parts
                    # Main object
                    try:
                        animation = t + 'animation: ' + str(o['animation']) + n
                        fixedobject = t + 'FixedObject: ' + str(o['fixedobject']) + n
                        obstacle = t + 'Obstacle: ' + str(o['obstacle']) + n
                        gfxonly = t + 'GfxOnly: ' + str(o['gfxonly']) + n
                        drivable = t + 'Drivable: ' + str(o['drivable']) + n
                        far = t + 'Far: ' + str(o['far']) + n + e
                    except:
                        print("Writing template failed:", o.name) # TODO: Fix this, some issue with l_prop_alpha_tree_02x_breakpart01 for example
                elif o.hide_viewport:
                    # Part
                    part_ctr += 1
                    part = t + 'part ' + str(part_ctr) + ' {' + n
                    part += t + t + 'name: ' + o.name + n
                    offset = translate_vector3(o.location)
                    offset = f"{t.join(f'{v:.6f}' for v in offset)}"
                    part += t + t + 'offset: ' + offset + ' ' + n
                    part += t + '}' + n
                    parts += part
            
            numparts = t + 'numparts: ' + str(part_ctr) + n
            
            lines.append(prop_template)
            lines.append(animation)
            lines.append(numparts)
            lines.append(parts)
            lines.append(fixedobject)
            lines.append(obstacle)
            lines.append(gfxonly)
            lines.append(drivable)
            lines.append(far)
        
        # Write props
        def write_props(objects):
            for prop in objects:
                name, ext = prop.name.rsplit('.')
                template = prop.instance_collection.name

                title = 'prop ' + str(ext) + ' {' + n
                matrix_start = t + 'matrix {' + n

                # Convert world matrix to Matrix34
                matrix = to_matrix34(prop.matrix_world)

                row1 = (matrix[0][0], matrix[1][0], matrix[2][0])
                row2 = (matrix[0][1], matrix[1][1], matrix[2][1])
                row3 = (matrix[0][2], matrix[1][2], matrix[2][2])
                row4 = (matrix[0][3], matrix[1][3], matrix[2][3])

                row1 = t + t + vector3_to_string(round_vector3(row1), '\t') + ' ' + n
                row2 = t + t + vector3_to_string(round_vector3(row2), '\t') + ' ' + n
                row3 = t + t + vector3_to_string(round_vector3(row3), '\t') + ' ' + n
                row4 = t + t + vector3_to_string(round_vector3(row4), '\t') + ' ' + n

                matrix_end = t + t + e

                template = t + t + 'prop_template: ' + template + n + e

                lines.append(title)
                lines.append(matrix_start)

                lines.append(row1)
                lines.append(row2)
                lines.append(row3)
                lines.append(row4)

                lines.append(matrix_end)
                lines.append(template)

        write_props(props_col.all_objects)
        write_props(props_fixed_col.all_objects)
        write_props(props_gfx_col.all_objects)

        # TODO: Check why prop files don't match still

        fp = os.path.join(city_path, map_name + '.prop')
        make_backup(fp)
        write_file(fp, lines)

        self.report({'INFO'}, f"Exported {map_name} props")
        return {'FINISHED'}

classes = (
    MC2_OT_SetupScene,
    MC2_OT_ClearScene,
    MC2_OT_RestoreBackup,
    MC2_OT_ImportCityModels,
    MC2_OT_ImportProps_Old,
    MC2_OT_ImportProps,
    MC2_OT_SpawnCityModels,
    MC2_OT_SpawnProps,
    MC2_OT_ExportHoods,
    MC2_OT_ExportProps,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
