import bpy, bmesh
import os
from .utils import translate_vector3, translate_uv, try_load_texture
#from bpy_extras import node_shader_utils

class ModMaterial:
    def __init__(self):
        self.name = None
        self.packet_count = 0
        self.primitive_count = 0
        self.texture_count = 0
        self.illum = None
        self.ambient = (0.0, 0.0, 0.0)
        self.diffuse = (1.0, 1.0, 1.0)
        self.specular = (0.0, 0.0, 0.0)
        self.textures = []
        self.material = None
        self.packets = []

class ModPacket:
    def __init__(self):
        self.num_adjs = 0
        self.num_prims = 0
        self.adjuncts = []
        self.primitives = []

def triangle_strip_to_list(strip, clockwise):
    triangle_list = []
    for v in range(len(strip) - 2):
        if clockwise:
            triangle_list.extend([strip[v+1], strip[v], strip[v+2]])
        else:
            triangle_list.extend([strip[v], strip[v+1], strip[v+2]])
        clockwise = not clockwise

    return triangle_list

def parse_primitive_tri(prim_type, indices):
    indices_ints = [int(x) for x in indices]
    triangles = None

    if prim_type == 'tri':
        triangles = indices_ints
    elif prim_type == 'str':
        indices_ints = indices_ints[1:]
        triangles = triangle_strip_to_list(indices_ints, False)
    elif prim_type == 'stp':
        indices_ints = indices_ints[1:]
        triangles = triangle_strip_to_list(indices_ints, True)
    else:
        raise Exception(f'Invalid primitive type {prim_type}')

    return triangles

def load_node_group(name: str, blend_file: str = "node_groups.blend") -> bpy.types.NodeTree | None:
    # Check if already loaded
    if name in bpy.data.node_groups:
        return bpy.data.node_groups[name]

    # Resolve path to resources folder next to this script
    addon_dir = os.path.dirname(__file__)
    blend_path = os.path.join(addon_dir, "resources", blend_file)

    if not os.path.exists(blend_path):
        print(f"Resource blend file not found: {blend_path}")
        return None

    # Append the node group
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        if name not in data_from.node_groups:
            print(f"[MC2] Node group '{name}' not found in {blend_path}")
            return None
        data_to.node_groups = [name]

    return bpy.data.node_groups.get(name)

def import_xmod(filepath, has_xbcpv = True):
    mc2_dir = bpy.context.scene.mc2_props.mc2_dir
    with open(filepath, 'r') as file:        
        # Parse xmod
        lines = file.read().splitlines()
        
        verts = []
        normals = []
        normals_remapped = []
        colors = []
        tex1s = []

        mod_materials = []
        mod_packets = []

        xbcpv_id_lists = []
        xbcpv_ids = []

        # Read and parse file lines
        for l_idx, l in enumerate(lines):
            if l.startswith('v\t'): # Read and add verts
                tok = l.split()
                vert = translate_vector3((float(tok[1]), float(tok[2]), float(tok[3])))
                verts.append(vert)
            
            if l.startswith('n\t'): # Read normals
                tok = l.split()
                normals.append(translate_vector3((float(tok[1]), float(tok[2]), float(tok[3]))))
            
            if l.startswith('c\t'): # Read colors
                tok = l.split()
                colors.append((float(tok[1]), float(tok[2]), float(tok[3]), float(tok[4])))
                
            if l.startswith('t1\t'): # Read UVs
                tok = l.split()
                tex1s.append(translate_uv((float(tok[1]), float(tok[2]))))
            
            if l.startswith('mtl'): # Read materials
                mod_mat = ModMaterial()
                mod_mat.name = l.split()[1]
                
                # Read material block
                for i in range(16):
                    idx = l_idx + i
                    line_tok = lines[idx].split()

                    if line_tok[0].startswith('}'): break
                    if line_tok[0].startswith('packets:'): mod_mat.packet_count = int(line_tok[1])
                    if line_tok[0].startswith('primitives:'): mod_mat.primitive_count = int(line_tok[1])
                    if line_tok[0].startswith('textures:'): mod_mat.texture_count = int(line_tok[1])
                    if line_tok[0].startswith('illum:'): mod_mat.illum = line_tok[1]
                    if line_tok[0].startswith('ambient:'): mod_mat.ambient = (eval(line_tok[1]), eval(line_tok[2]), eval(line_tok[3])) # Read float array/vec3 func to make it cleaner?
                    if line_tok[0].startswith('diffuse:'): mod_mat.diffuse = (eval(line_tok[1]), eval(line_tok[2]), eval(line_tok[3]))
                    if line_tok[0].startswith('specular:'): mod_mat.specular = (eval(line_tok[1]), eval(line_tok[2]), eval(line_tok[3]))

                    # Add all textures into an array, however only the first one will be used
                    if line_tok[0].startswith('texture:'):
                        texture_name = line_tok[2]
                        texture_name = texture_name[1:][:-1] # Removes parentheses
                        mod_mat.textures.append(texture_name)
                
                mod_materials.append(mod_mat)
            
            # Read packets
            if l.startswith('packet '):
                mod_packet = ModPacket()
                packet_tok = l.split()
                mod_packet.num_adjs = int(packet_tok[1])
                mod_packet.num_prims = int(packet_tok[2])

                # Adjunct format: vidx, nidx, cidx, u1idx, u2idx, mtx
                idx = l_idx + 1
                mod_packet.adjuncts = lines[idx:idx + mod_packet.num_adjs]
                idx += mod_packet.num_adjs
                mod_packet.primitives = lines[idx:idx + mod_packet.num_prims] # '\tstr     4    0    1    2    3\n' or without \t\n

                mod_packets.append(mod_packet)
        # Xmod parse end
        
        # Associate packets to materials
        packet_idx = 0
        for mod_mat in mod_materials:
            for packet in range(mod_mat.packet_count):
                mod_mat.packets.append(mod_packets[packet_idx])
                packet_idx += 1
        
        # Place materials without textures last, so if there are duplicate/faulty faces, the textured ones get priority
        solid_mats = [] # Temp list used to place solid materials at the end

        cpv_id_offsets = [] # List of offsets, used when placing solid/textureless materials at the end, so that the xbcpv file later on knows about these offsets
        solid_mat_adj_ctr = 0

        for mod_mat in mod_materials:
            if mod_mat.texture_count == 0:
                for packet in mod_mat.packets:
                    solid_mat_adj_ctr += packet.num_adjs
                solid_mats.append(mod_mat)
                mod_materials.remove(mod_mat) # Remove solid material from this spot
            cpv_id_offsets.append(solid_mat_adj_ctr) # Note the total offset for this material
        mod_materials.extend(solid_mats) # Re-add solid material at the end

        # Set up materials and textures
        for mod_mat in mod_materials:
            for tex in mod_mat.textures:
                if tex in bpy.data.materials:
                    # print('Material found: ' + tex)
                    mod_mat.material = bpy.data.materials[tex]
                else:
                    print('Material NOT found, creating: ' + tex)
                    newmat = bpy.data.materials.new(tex)

                    texture = try_load_texture(tex, os.path.join(mc2_dir, 'texture_x'))

                    newmat.use_nodes = True
                    nodetree = newmat.node_tree

                    for node in nodetree.nodes:
                        if node.type == 'BSDF_PRINCIPLED':
                            nodetree.nodes.remove(node)
                            break

                    shader_node = nodetree.nodes.new('ShaderNodeGroup')
                    shader_node.node_tree = load_node_group('mc2_base_material')#, 'node_groups') #bpy.data.node_groups['mc2_base_material'] # Import from external file
                    shader_node.location = (50, 300)

                    tex_node = nodetree.nodes.new('ShaderNodeTexImage')
                    tex_node.image = texture
                    tex_node.location = (-300, 300)

                    nodetree.links.new(tex_node.outputs[0], shader_node.inputs[0])
                    nodetree.links.new(shader_node.outputs[2], nodetree.nodes.get('Material Output').inputs[0])

                    #newmat_wrapper = node_shader_utils.PrincipledBSDFWrapper(newmat, is_readonly=False)
                    #newmat_wrapper.base_color = mod_mat.diffuse
                    # newmat_wrapper.specular = sum(mod_mat.specular) / 3.0
                    # newmat_wrapper.roughness = (1.0 - shininess)
                    #newmat_wrapper.base_color_texture.image = texture

                    mod_mat.material = newmat
                break # Only process the first texture (tex1)

        # Set up mesh
        #scn = bpy.context.scene
        # Get filename from path
        xmod_name = os.path.splitext(os.path.basename(filepath))[0]
        me = bpy.data.meshes.new(xmod_name)
        obj = bpy.data.objects.new(xmod_name, me)
        bm = bmesh.new()
        bm.from_mesh(me)
        #scn.collection.objects.link(obj)
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
        
        # Store current mode and switch to Edit
        current_mode = bpy.context.object.mode
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        
        # Create empty UV and VCol layers
        uv_layer = bm.loops.layers.uv.new()
        vcol_layer = bm.loops.layers.color.new()

        # Create verts
        for v in verts:
            bm.verts.new(v) # Can these be created later when things are verified somehow?
        
        adj_ctr = 0 # Adjunct counter used for cpvs
        tris_check = [] # Collect tri info from all materials for mesh integrity checks

        # Create faces associated to mod materials
        for mat_idx, mod_mat in enumerate(mod_materials):
            # Append material to the object
            obj.data.materials.append(mod_mat.material)
            mat_used = False
            mat_xbcpv_ids = [] # CPV IDs for this material

            for packet in mod_mat.packets:
                for prim in packet.primitives:
                    prim_tok = prim.split() # ['str', '4', '0', '1', '2', '3']
                    adj_indices = parse_primitive_tri(prim_tok[0], prim_tok[1:]) # [0, 1, 2, 2, 1, 3]

                    for y in range(0, len(adj_indices), 3): # Executes twice if it's 4 numbers for example
                        adj_tri = adj_indices[y:y+3] # [0, 1, 2], then [2, 1, 3]
                        tri_verts = []
                        tri_normals = []
                        tri_colors = []
                        tri_tex1s = []
                        
                        for adj_idx in adj_tri:
                            vert_idx = int(packet.adjuncts[adj_idx].split()[1])
                            tri_verts.append(vert_idx)
                            normal_idx = int(packet.adjuncts[adj_idx].split()[2])
                            tri_normals.append(normal_idx)
                            col_idx = int(packet.adjuncts[adj_idx].split()[3])
                            tri_colors.append(col_idx)
                            tex1_idx = int(packet.adjuncts[adj_idx].split()[4])
                            tri_tex1s.append(tex1_idx)
                        
                        # Mesh integrity checks
                        tri_verts_sorted = sorted(tri_verts)
                        if not tri_verts_sorted in tris_check and not tri_verts[0] == tri_verts[1]:
                            tris_check.append(tri_verts_sorted)
                            mat_used = True
                        else:
                            print('Skipping faulty primitive on', xmod_name, tri_verts)
                            continue # Skip this primitive
                        
                        # Tri verts to bmesh
                        tri_verts_bm = []
                        bm.verts.ensure_lookup_table()
                        for vert_idx in tri_verts:
                            tri_verts_bm.append(bm.verts[vert_idx])
                        
                        tri = bm.faces.new(tri_verts_bm)
                        
                        # Re-map normals according to adjuncts
                        for normal_idx in tri_normals:
                            normals_remapped.append(normals[normal_idx])
                        
                        # Store CPV indices
                        if has_xbcpv: mat_xbcpv_ids.extend([x + adj_ctr for x in adj_tri]) # IDs get reset per material, we keep track of total adjunct count here
                        
                        # Assign current material index to this face
                        tri.material_index = mat_idx

                        # Mark face as smooth
                        tri.smooth = True

                        # Apply data to face corners
                        for i in range(len(tri.loops)):
                            # Apply UVs
                            tri.loops[i][uv_layer].uv = tex1s[tri_tex1s[i]]
                            # Apply xmod colors
                            tri.loops[i][vcol_layer] = colors[tri_colors[i]]

                adj_ctr += packet.num_adjs
            
            # Unused material check
            if not mat_used:
                print('Removing unused material', mod_mat.name)
                bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
                bpy.context.object.active_material_index = mat_idx
                bpy.ops.object.material_slot_remove()
                bpy.ops.object.mode_set(mode='EDIT', toggle=False)
            
            if has_xbcpv: xbcpv_id_lists.append(mat_xbcpv_ids) # Append CPVs from the material into the actual CPV array
        
        if has_xbcpv:
            # Reorder the CPV lists because solid materials get placed last
            for mat_idx in range(len(xbcpv_id_lists)):
                if mod_materials[mat_idx].texture_count == 0:
                    textureless_cpvs = xbcpv_id_lists[mat_idx]
                    xbcpv_id_lists.pop(mat_idx)
                    xbcpv_id_lists.append(textureless_cpvs)
                else:
                    # For example, if the first material is solid/textureless, and has 4 adjuncts,
                    # the material gets moved to the end of the materials list, because we prioritize textured materials first,
                    # but the xbcpv file doesn't know about this,
                    # this will give the following IDs an additional offset of 4 to make up for this,
                    # which is important for the IDs found in the xbcpv file.
                    temp_list = xbcpv_id_lists[mat_idx]
                    xbcpv_id_lists[mat_idx] = [x + cpv_id_offsets[mat_idx] for x in temp_list]

            # Make the CPV IDs a single array, instead of a list of arrays
            for list in xbcpv_id_lists:
                xbcpv_ids.extend(list)

    # Store CPV indices as a custom int array property
    if (has_xbcpv):
        obj['CPV IDs'] = xbcpv_ids
    
    # Calculate normals
    # bm.normal_update() # ?
    
    # Reset mode
    bpy.ops.object.mode_set(mode = current_mode)
    
    # Free resources
    bm.to_mesh(me)
    bm.free()

    # Apply custom normals
    me.normals_split_custom_set(normals_remapped)

    # Clean up attribute layers
    obj.data.uv_layers.active.name = 'UVMap'
    obj.data.vertex_colors[0].name = 'CPV'
    obj.data.vertex_colors.active_index = 0
        
    # Return created object
    return obj

def import_xbcpv(filepath, obj):
    with open(filepath, 'rb') as f:
        header = f.read(4)
        mat_count = int.from_bytes(f.read(4), 'little')
        cpvs = []

        for mat_idx in range(mat_count):
            adj_count = int.from_bytes(f.read(4), 'little')
            for cpv in range(adj_count):
                r = int.from_bytes(f.read(1), 'little') / 255
                g = int.from_bytes(f.read(1), 'little') / 255
                b = int.from_bytes(f.read(1), 'little') / 255
                a = int.from_bytes(f.read(1), 'little') / 255

                cpvs.append((b, g, r, a)) # BGRA to RBGA
        
        # Apply CPVs
        mesh = obj.data
        current_mode = bpy.context.object.mode # Store current mode and switch to Edit
        bpy.ops.object.mode_set(mode='EDIT', toggle=False)
        bm = bmesh.from_edit_mesh(mesh)

        cpv_ids = obj['CPV IDs']
        cpv_layer = bm.loops.layers.color['CPV']

        temp_ctr = 0
        for face in bm.faces:
            for i in range(len(face.loops)): # Iterating through face corners (adjuncts)
                id = cpv_ids[temp_ctr]

                face.loops[i][cpv_layer] = cpvs[id]

                temp_ctr += 1

        bpy.ops.object.mode_set(mode = current_mode) # Reset mode