import bpy
import os
import math
import time
from mathutils import Vector
from .utils import fmt_zero, convert_vec3, write_file, make_backup

time1 = time.perf_counter()

# EXPORT
class OTCellExport:
    def __init__(self, bmin, bmax, polys, depth=0):
        self.bmin = bmin
        self.bmax = bmax
        self.polys = polys
        self.depth = depth

def convert_bbox(bmin, bmax):
    corners = [
        convert_vec3((x, y, z))
        for x in (bmin[0], bmax[0])
        for y in (bmin[1], bmax[1])
        for z in (bmin[2], bmax[2])]
    
    amin = (
        min(c[0] for c in corners),
        min(c[1] for c in corners),
        min(c[2] for c in corners))
    
    amax = (
        max(c[0] for c in corners),
        max(c[1] for c in corners),
        max(c[2] for c in corners))
    return amin, amax

# Octree split logic
def split_cell_exact(cell):
    xmin, ymin, zmin = cell.bmin
    xmax, ymax, zmax = cell.bmax

    mx = (xmin + xmax) * 0.5
    my = (ymin + ymax) * 0.5
    mz = (zmin + zmax) * 0.5

    children = []

    for dz in (0, 1):         # far -> near
        for dy in (0, 1):     # bottom -> top
            for dx in (0, 1): # left -> right
                bmin = (
                    mx if dx == 0 else xmin,
                    ymin if dy == 0 else my,
                    zmin if dz == 0 else mz)
                
                bmax = (
                    xmax if dx == 0 else mx,
                    my if dy == 0 else ymax,
                    mz if dz == 0 else zmax)
                
                children.append(OTCellExport(bmin, bmax, [], cell.depth + 1))
    return children

def poly_overlaps_cell_old(poly_index, cell, verts_ws, obj):
    xmin, ymin, zmin = cell.bmin
    xmax, ymax, zmax = cell.bmax
    for vi in obj.data.polygons[poly_index].vertices:
        v = verts_ws[vi]
        if xmin <= v.x <= xmax and ymin <= v.y <= ymax and zmin <= v.z <= zmax:
            return True
    return False

def poly_overlaps_cell(poly_index, cell, verts_ws, obj, poly_bboxes):
    (pbmin, pbmax) = poly_bboxes[poly_index]

    xmin, ymin, zmin = cell.bmin
    xmax, ymax, zmax = cell.bmax

    # AABB reject
    if (pbmax[0] < xmin or pbmin[0] > xmax or
        pbmax[1] < ymin or pbmin[1] > ymax or
        pbmax[2] < zmin or pbmin[2] > zmax):
        return False

    poly = obj.data.polygons[poly_index]
    verts = [verts_ws[v] for v in poly.vertices]

    # Plane vs AABB
    n = poly.normal
    d = -n.dot(verts[0])

    cx = (xmin + xmax) * 0.5
    cy = (ymin + ymax) * 0.5
    cz = (zmin + zmax) * 0.5

    ex = (xmax - xmin) * 0.5
    ey = (ymax - ymin) * 0.5
    ez = (zmax - zmin) * 0.5

    r = abs(n.x)*ex + abs(n.y)*ey + abs(n.z)*ez
    s = n.dot(Vector((cx, cy, cz))) + d

    if abs(s) > r:
        return False

    # Edge vs AABB
    cell_min = Vector(cell.bmin)
    cell_max = Vector(cell.bmax)

    def seg_aabb(p0, p1):
        t0, t1 = 0.0, 1.0
        d = p1 - p0
        for i in range(3):
            if abs(d[i]) < 1e-8:
                if p0[i] < cell_min[i] or p0[i] > cell_max[i]:
                    return False
            else:
                ood = 1.0 / d[i]
                tmin = (cell_min[i] - p0[i]) * ood
                tmax = (cell_max[i] - p0[i]) * ood
                if tmin > tmax:
                    tmin, tmax = tmax, tmin
                t0 = max(t0, tmin)
                t1 = min(t1, tmax)
                if t0 > t1:
                    return False
        return True

    for i in range(len(verts)):
        if seg_aabb(verts[i], verts[(i+1) % len(verts)]):
            return True

    # Cell corner inside polygon (2D projection test)
    # Project to dominant plane of polygon normal
    n = poly.normal
    ax = max(range(3), key=lambda i: abs(n[i]))
    axes = [0, 1, 2]
    axes.remove(ax)
    u, v = axes

    poly_2d = [(p[u], p[v]) for p in verts]

    def point_in_poly_2d(pt):
        inside = False
        x, y = pt
        j = len(poly_2d) - 1
        for i in range(len(poly_2d)):
            xi, yi = poly_2d[i]
            xj, yj = poly_2d[j]
            if ((yi > y) != (yj > y)) and \
               (x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi):
                inside = not inside
            j = i
        return inside

    for x in (xmin, xmax):
        for y in (ymin, ymax):
            for z in (zmin, zmax):
                p = (x, y, z)
                if point_in_poly_2d((p[u], p[v])):
                    return True
    return False

# Octree builder
def compute_poly_bboxes(obj, verts_ws):
    bboxes = []
    for poly in obj.data.polygons:
        vs = [verts_ws[v] for v in poly.vertices]
        bboxes.append((
            (min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)),
            (max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs))))
    return bboxes

def build_octree(bmin, bmax, polys, obj, verts_ws, poly_bboxes, max_depth=10, max_polys=22):
    stream = []
    min_cell_size = float("inf")

    def recurse(cell):
        nonlocal min_cell_size
        xmin, ymin, zmin = cell.bmin
        xmax, ymax, zmax = cell.bmax
        min_cell_size = min(min_cell_size, xmax - xmin, ymax - ymin, zmax - zmin)

        if len(cell.polys) <= max_polys or cell.depth >= max_depth:
            stream.append(("t", list(cell.polys)))
            return

        stream.append(("s", None))
        children = split_cell_exact(cell)
        for child in children:
            child.polys = [pi for pi in cell.polys if poly_overlaps_cell(pi, child, verts_ws, obj, poly_bboxes)]
            recurse(child)

    root = OTCellExport(bmin, bmax, polys, 0)
    recurse(root)
    return stream, min_cell_size

# Main export function
def export_otgrid_bnd(obj, fp):
    if obj is None or obj.type != "MESH":
        raise RuntimeError("Select a mesh object")

    mesh = obj.data
    verts_ws = [obj.matrix_world @ v.co for v in mesh.vertices]

    # Max values for a single cell
    max_ot_verts = 0
    max_ot_edges = 0
    max_ot_polys = 0

    poly_bboxes = compute_poly_bboxes(obj, verts_ws)

    cell_dim = 500.0

    # Assign polygons to grid cells
    cell_polys = {}
    for pi, poly in enumerate(mesh.polygons):
        used = set()
        for vi in poly.vertices:
            v = verts_ws[vi]
            gx = math.floor(v.x / cell_dim)
            gy = math.floor(v.y / cell_dim)
            key = (gx, gy)
            if key not in used:
                cell_polys.setdefault(key, []).append(pi)
                used.add(key)

    # Compute grid bounds for CellDim Min/Max X/Z
    if cell_polys:
        min_gx = min(k[0] for k in cell_polys)
        max_gx = max(k[0] for k in cell_polys)
        min_gy = min(k[1] for k in cell_polys)
        max_gy = max(k[1] for k in cell_polys)
    else:
        min_gx = max_gx = min_gy = max_gy = 0

    age_min_x = - (max_gx + 1)
    age_max_x = - min_gx - 1
    age_min_z = min_gy
    age_max_z = max_gy

    # Build parent cells in top-left -> bottom-right order
    parents = []
    for gz in range(max_gy, min_gy - 1, -1): # top -> bottom
        for gx in range(min_gx, max_gx + 1): # left -> right
            polys = cell_polys.get((gx, gz), [])
            if polys:
                min_x = min(verts_ws[vi].x for pi in polys for vi in mesh.polygons[pi].vertices)
                max_x = max(verts_ws[vi].x for pi in polys for vi in mesh.polygons[pi].vertices)
                min_y = min(verts_ws[vi].y for pi in polys for vi in mesh.polygons[pi].vertices)
                max_y = max(verts_ws[vi].y for pi in polys for vi in mesh.polygons[pi].vertices)
                min_z = min(verts_ws[vi].z for pi in polys for vi in mesh.polygons[pi].vertices)
                max_z = max(verts_ws[vi].z for pi in polys for vi in mesh.polygons[pi].vertices)

                side = max(max_x - min_x, max_y - min_y, max_z - min_z)
                cx = (min_x + max_x) * 0.5
                cy = (min_y + max_y) * 0.5
                cz = (min_z + max_z) * 0.5
                half = side * 0.5

                bmin = (cx - half, cy - half, cz - half)
                bmax = (cx + half, cy + half, cz + half)
            else:
                bmin = bmax = (0.0, 0.0, 0.0)

            parents.append((bmin, bmax, polys))
    parents = list(reversed(parents)) # Reverse the list

    # Write .bnd file
    lines = [
        "version: 1.10\n",
        "type: otgrid\n\n",
        f"CellDim: {cell_dim:.6f} \n",
        f"MinX: {age_min_x} \n",
        f"MaxX: {age_max_x} \n",
        f"MinZ: {age_min_z} \n",
        f"MaxZ: {age_max_z} \n"]

    for bmin, bmax, polys in parents:
        if not polys:
            lines.append("\nverts: 0 \n")
            lines.extend([
                "otNumCells: 1 \n",
                "otNumPolys: 0 \n",
                "otBoxMin: 0.000000\t0.000000\t0.000000 \n",
                "otBoxMax: 0.000000\t0.000000\t0.000000 \n",
                "otMaxHeight: 8 \n",
                "otMaxPerCell: 22 \n",
                "otMaxDuplication: 3.000000 \n",
                "otMinCellSize: 0.000000 \n",
                "t 0\n"])
            continue

        amin, amax = convert_bbox(bmin, bmax)

        # Setup verts
        vert_map = {}
        vert_list = []
        for pi in polys:
            for vi in mesh.polygons[pi].vertices:
                if vi not in vert_map:
                    vert_map[vi] = len(vert_list)
                    vert_list.append(vi)
        
        # Collect materials used in this cell
        mat_map = {}  # Blender material -> local index
        mat_list = [] # Ordered list of materials

        for pi in polys:
            poly = mesh.polygons[pi]
            mat_index = poly.material_index
            if mat_index < len(mesh.materials):
                mat = mesh.materials[mat_index]
            else:
                mat = None

            if mat not in mat_map:
                mat_map[mat] = len(mat_list)
                mat_list.append(mat)

        # Setup edges
        # TODO: Check/fix edge normals
        edges = []
        edge_lookup = {}
        seen = set()
        for pi in polys:
            poly = mesh.polygons[pi]
            vs = poly.vertices
            for i in range(len(vs)):
                a = vert_map[vs[i]]
                b = vert_map[vs[(i+1)%len(vs)]]
                key = tuple(sorted((a,b)))
                if key in seen: continue
                seen.add(key)

                v0 = verts_ws[vs[i]]
                v1 = verts_ws[vs[(i+1)%len(vs)]]
                ax0, ay0, az0 = convert_vec3((v0.x, v0.y, v0.z))
                ax1, ay1, az1 = convert_vec3((v1.x, v1.y, v1.z))
                dx, dz = ax1-ax0, az1-az0
                nx, nz = -dz, dx
                l = math.hypot(nx, nz)
                if l: nx/=l; nz/=l

                edge_lookup[key] = len(edges)
                edges.append((a,b,nx,0.0,nz))

        # Geometry output
        lines.append(f"\nverts: {len(vert_list)} \n\n")
        lines.append(f"materials: {len(mat_list)} \nedges: {len(edges)} \npolys: {len(polys)} \nreadedgenormals: 1 \n\n")

        for vi in vert_list:
            v = verts_ws[vi]
            ax, ay, az = convert_vec3((v.x,v.y,v.z))
            lines.append(f"v {ax:.6f} {ay:.6f} {az:.6f} \n")
        
        # Update max values
        max_ot_verts = max(max_ot_verts, len(vert_list))
        max_ot_edges = max(max_ot_edges, len(edges))
        max_ot_polys = max(max_ot_polys, len(polys))

        # Write materials
        lines.append("\n")

        for mat in mat_list:
            # Fallback defaults
            elasticity = 0.0
            friction = 0.0
            effect = -1
            sound = -1
            drag = 0.0
            width = 0.0
            height = 0.0
            depth = 0.0
            ptxindex = (-1, -1)
            ptxthreshold = (0.0, 0.0)
            sndfx = 0

            if mat and mat.node_tree:
                nodes = mat.node_tree.nodes

                def val(name, default=0.0):
                    n = nodes.get(name)
                    return n.outputs[0].default_value if n else default

                elasticity = round(val("elasticity", 0.0), 6)
                friction   = round(val("friction", 0.0), 6)
                effect     = int(val("effect", -1))
                sound      = int(val("sound", -1))
                drag       = round(val("drag", 0.0), 6)
                width      = round(val("width", 0.0), 6)
                height     = round(val("height", 0.0), 6)
                depth      = round(val("depth", 0.0), 6)

                ptxindex = (
                    int(val("ptxindex0", -1)),
                    int(val("ptxindex1", -1)))

                ptxthreshold = (
                    round(val("ptxthreshold0", 0.0), 6),
                    round(val("ptxthreshold1", 0.0), 6))

                sndfx = int(val("SndFx", 0))

            mat_name = mat.name if mat else "default"

            lines.append(
                "type: BASE\n"
                f"mtl {mat_name} {{\n"
                f"\telasticity: {elasticity:.6f} \n"
                f"\tfriction: {friction:.6f} \n"
                f"\teffect: {effect} \n"
                f"\tsound: {sound} \n"
                f"\tdrag: {drag:.6f} \n"
                f"\twidth: {width:.6f} \n"
                f"\theight: {height:.6f} \n"
                f"\tdepth: {depth:.6f} \n"
                f"\tptxindex: {ptxindex[0]}  {ptxindex[1]} \n"
                f"\tptxthreshold: {ptxthreshold[0]:.6f}  {ptxthreshold[1]:.6f} \n"
                f"\tSndFx: {sndfx} \n"
                "}\n\n")

        # Write edges
        for a,b,nx,ny,nz in edges:
            lines.append(f"edge {a} {b} {fmt_zero(nx)}\t{fmt_zero(ny)}\t{fmt_zero(nz)} \n")
        lines.append("\n")

        # Write faces
        for pi in polys:
            poly = mesh.polygons[pi]
            vs = [vert_map[v] for v in poly.vertices]
            es = [edge_lookup[tuple(sorted((vs[i], vs[(i+1)%len(vs)])))] for i in range(len(vs))]

            mat = mesh.materials[poly.material_index] if poly.material_index < len(mesh.materials) else None
            mat_id = mat_map.get(mat, 0)

            if len(vs) == 3:
                lines.append(
                    f"tri {vs[0]} {vs[1]} {vs[2]} {mat_id} "
                    f"{es[0]} {es[1]} {es[2]} \n")
            elif len(vs) == 4:
                lines.append(
                    f"quad {vs[0]} {vs[1]} {vs[2]} {vs[3]} {mat_id} "
                    f"{es[0]} {es[1]} {es[2]} {es[3]} \n")

        lines.append("\n")

        # Octree
        octree, min_cell = build_octree(bmin, bmax, polys, obj, verts_ws, poly_bboxes)
        lines.extend([
            f"otNumCells: {len(octree)} \n",
            f"otNumPolys: {sum(len(n[1]) for n in octree if n[0]=='t')} \n",
            f"otBoxMin: {fmt_zero(amin[0])}\t{fmt_zero(amin[1])}\t{fmt_zero(amin[2])} \n",
            f"otBoxMax: {fmt_zero(amax[0])}\t{fmt_zero(amax[1])}\t{fmt_zero(amax[2])} \n",
            "otMaxHeight: 8 \n",
            "otMaxPerCell: 22 \n",
            "otMaxDuplication: 3.000000 \n",
            f"otMinCellSize: {min_cell:.6f} \n"])

        # Parent-local polygon index map
        local_poly_index = {pi: i for i, pi in enumerate(polys)}

        for kind, faces in octree:
            if kind == "s":
                lines.append("s ")
            else:
                if faces:
                    lines.append(
                        "t " + str(len(faces)) + " " +
                        " ".join(str(local_poly_index[pi]) for pi in faces) + "\n")
                else:
                    lines.append("t 0\n")

    # Write main .bnd
    make_backup(fp)
    write_file(fp, lines)

    # If not quad_0
    basename = os.path.basename(fp)
    if 'quad_0' not in basename: # TODO: Verify this
        # Write .bndmax
        bndmax_fp = fp + "max"
        max_lines = [
            f"maxOtEdges: {max_ot_edges}\n",
            f"maxOtPolys: {max_ot_polys}\n",
            f"maxOtVerts: {max_ot_verts}\n"]            
            
        make_backup(bndmax_fp)
        write_file(bndmax_fp, max_lines)

    #print("Export done:", fp)
    #print("Total time: %.4f sec." % (time.perf_counter()-time1))

# IMPORT
class CellImport:
    def __init__(self, verts, mtls, faces):
        self.verts = verts
        self.mtls = mtls
        self.faces = faces

def extract_mtl_name(s):
    tok = s.split()
    mat_name = tok[1]
    if ':' in mat_name: return mat_name.rsplit(':', 1)[1]
    else: return mat_name

def load_physics_materials():
    addon_dir = os.path.dirname(__file__)
    rsc_blend_path = os.path.join(addon_dir, "resources", "node_groups.blend")
    ph_mats_obj_name = 'Physics_Materials'

    existing_mats = {m.name for m in bpy.data.materials}

    # Link object ONLY to inspect its material slots
    with bpy.data.libraries.load(rsc_blend_path, link=True) as (src, dst):
        if ph_mats_obj_name not in src.objects:
            return
        dst.objects = [ph_mats_obj_name]

    obj = dst.objects[0]
    if not obj:
        return

    # Find missing materials
    missing_mats = {
        slot.material.name
        for slot in obj.material_slots
        if slot.material and slot.material.name not in existing_mats}

    # Append only missing materials
    if missing_mats:
        with bpy.data.libraries.load(rsc_blend_path, link=False) as (src, dst):
            dst.materials = list(missing_mats)
        
        # Mark as fake user
        for name in missing_mats:
            mat = bpy.data.materials.get(name)
            if mat: mat.use_fake_user = True

    # Cleanup linked object
    bpy.data.objects.remove(obj)

def build_collision_mesh(cells, name='collider'):
    mesh = bpy.data.meshes.new(name)
    obj  = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj

    # Material handling
    mat_index_map = {} # Material name -> global index

    def get_mat_index(mat_name):
        if mat_name not in mat_index_map:
            mat = bpy.data.materials.get(mat_name)
            if mat:
                mat_index_map[mat_name] = len(mesh.materials)
                mesh.materials.append(mat)
        return mat_index_map[mat_name]

    # Geometry buffers
    vert_map =  {} # Global index
    verts    =  []
    faces    =  []
    face_mats = []

    def get_vert_index(v):
        if v not in vert_map:
            vert_map[v] = len(verts)
            verts.append(v)
        return vert_map[v]

    # Build mesh
    for cell in cells:
        # Pre-resolve local material indices to global
        local_mat_map = [
            get_mat_index(name)
            for name in cell.mtls]

        for f in cell.faces:
            if len(f) == 5: # Quad
                idxs = f[:4]
                mat  = local_mat_map[f[4]]
            else:           # Tri
                idxs = f[:3]
                mat  = local_mat_map[f[3]]

            face = [get_vert_index(cell.verts[i]) for i in idxs]

            # Skip degenerate faces
            if len(set(face)) < 3:
                continue

            faces.append(face)
            face_mats.append(mat)

    # Create mesh
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    for poly, mat_idx in zip(mesh.polygons, face_mats):
        poly.material_index = mat_idx
    
    return obj

def import_bnd(fp):
    with open(fp) as f:
        lines = f.read()

        # Load missing physics materials
        load_physics_materials()

        cells = []
        cells_lines = lines.split('verts: ')[1:]
        for cell in cells_lines:
            verts = []
            mtls = []
            faces = []
            cell_lines = cell.splitlines()
            for line in cell_lines:
                if line.startswith('v '):
                    coords = line.split()
                    x = float(coords[1])
                    y = float(coords[2])
                    z = float(coords[3][:-2])
                    verts.append((-x, z, y))
                
                if line.startswith('mtl '):
                    mtls.append(extract_mtl_name(line))
                        
                if line.startswith('quad'):
                    ids = [int(s) for s in line.split() if s.isdigit()]
                    mat_idx = ids[4]
                    faces.append((ids[0], ids[1], ids[2], ids[3], mat_idx))
                if line.startswith('tri'):
                    ids = [int(s) for s in line.split() if s.isdigit()]
                    mat_idx = ids[3]
                    faces.append((ids[0], ids[1], ids[2], mat_idx))
            cells.append(CellImport(verts, mtls, faces))
        
        # Create mesh
        return build_collision_mesh(cells, os.path.basename(fp))
