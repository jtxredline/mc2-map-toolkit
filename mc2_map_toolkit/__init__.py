bl_info = {
    "name": "MC2 Map Toolkit",
    "author": "Redline",
    "version": (0, 0, 1),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > MC2 Map Toolkit",
    "description": "Set of tools for working with Midnight Club 2 maps",
    "category": "Object",
}

import bpy
import os
import importlib
from . import operators

from .utils import get_last_dir, get_last_map_name, write_file, validate_mc2_dir

# Reload support for development
importlib.reload(operators)

# Properties

def update_dir(self, context): # Update function for when mc2 directory is refreshed
    parent_dir = os.path.dirname(__file__)
    globals_path = os.path.join(parent_dir, 'globals.py')
    mc2_dir = bpy.context.scene.mc2_props.mc2_dir

    lines = []
    with open(globals_path, 'r') as file:
        for line in file.readlines():
            if line.startswith('mc2_dir = '):
                line = 'mc2_dir = "' + mc2_dir + "\"" + '\n'
            lines.append(line)
    write_file(globals_path, lines) # Write dir to file so it stays persistent

def update_map_name(self, context):
    parent_dir = os.path.dirname(__file__)
    globals_path = os.path.join(parent_dir, 'globals.py')
    map_name = bpy.context.scene.mc2_props.map_name

    lines = []
    with open(globals_path, 'r') as file:
        for line in file.readlines():
            if line.startswith('map_name = '):
                line = 'map_name = "' + map_name + "\"" + '\n'
            lines.append(line)
    write_file(globals_path, lines) # Write map name to file so it stays persistent


class MC2Properties(bpy.types.PropertyGroup):
    map_name: bpy.props.StringProperty(
        name="Map",
        description="Enter a map name or string",
        default=get_last_map_name(),
        update=update_map_name
    )

    mc2_dir: bpy.props.StringProperty(
        name="MC2 Dir",
        subtype='DIR_PATH',
        description="Directory path to Midnight Club 2 folder",
        default=get_last_dir(), # Read last used path from globals file
        update=update_dir
    )

# UI Panel

class MC2_PT_MainPanel(bpy.types.Panel):
    bl_label = "MC2 Map Editor"
    bl_idname = "MC2_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MC2"

    def draw(self, context):
        layout = self.layout
        props = context.scene.mc2_props

        layout.prop(props, "mc2_dir")

        valid, msg = validate_mc2_dir(props.mc2_dir)
        if not valid:
            row = layout.row()
            row.alert = True
            row.label(text=f"{msg}", icon="ERROR")

        layout.prop(props, "map_name")

        layout.separator()

        row = layout.column()
        #row.enabled = valid
        row.operator("mc2.setup_scene")
        row.operator("mc2.clear_scene")
        row.operator("mc2.restore_backup")
        row.separator()

        row.operator("mc2.import_city_models")
        row.operator("mc2.import_props")
        row.separator()

        row.operator("mc2.spawn_city_models")
        row.operator("mc2.spawn_props")
        row.separator()

        # Some kind of validate operator here?

        row.operator("mc2.export_hoods")
        row.operator("mc2.export_props")

# Registration

classes = (
    MC2Properties,
    MC2_PT_MainPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mc2_props = bpy.props.PointerProperty(type=MC2Properties)
    operators.register()

def unregister():
    operators.unregister()
    del bpy.types.Scene.mc2_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
