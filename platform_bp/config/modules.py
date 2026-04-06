MODULE_CATALOG = (
    {
        'code': 'students',
        'name': 'Students Management',
        'family': 'academic',
        'is_core': True,
        'is_addon': False,
        'sort_order': 10,
    },
    {
        'code': 'classes',
        'name': 'Classes And Streams',
        'family': 'academic',
        'is_core': True,
        'is_addon': False,
        'sort_order': 20,
    },
    {
        'code': 'exams',
        'name': 'Exams And Grading',
        'family': 'academic',
        'is_core': True,
        'is_addon': False,
        'sort_order': 30,
    },
    {
        'code': 'attendance',
        'name': 'Attendance Tracking',
        'family': 'academic',
        'is_core': True,
        'is_addon': False,
        'sort_order': 40,
    },
    {
        'code': 'fees',
        'name': 'Fees Collection And Management',
        'family': 'accounting',
        'is_core': True,
        'is_addon': False,
        'sort_order': 50,
    },
    {
        'code': 'finance',
        'name': 'Financial Accounting',
        'family': 'accounting',
        'is_core': True,
        'is_addon': False,
        'sort_order': 60,
    },
    {
        'code': 'inventory_uniform',
        'name': 'Inventory And Uniform Issuance',
        'family': 'operations',
        'is_core': False,
        'is_addon': True,
        'sort_order': 70,
    },
    {
        'code': 'procurement_assets',
        'name': 'Procurement And Assets',
        'family': 'operations',
        'is_core': False,
        'is_addon': True,
        'sort_order': 80,
    },
    {
        'code': 'fleet_transport',
        'name': 'Fleet And Transport',
        'family': 'operations',
        'is_core': False,
        'is_addon': True,
        'sort_order': 90,
    },
    {
        'code': 'farm_operations',
        'name': 'Farm Operations',
        'family': 'operations',
        'is_core': False,
        'is_addon': True,
        'sort_order': 100,
    },
)

BUNDLE_FAMILY_OPTIONS = (
    ('academic', 'Academic'),
    ('accounting', 'Accounting'),
    ('combined', 'Combined'),
)

DEFAULT_BUNDLE_MODULE_CODES = {
    'academic': ['students', 'classes', 'exams', 'attendance'],
    'accounting': ['fees', 'finance'],
    'combined': ['students', 'classes', 'exams', 'attendance', 'fees', 'finance'],
}

MODULE_FAMILY_LABELS = {
    'academic': 'Academic',
    'accounting': 'Accounting',
    'operations': 'Operations',
    'admin': 'Administration',
}

MODULE_FAMILY_COLORS = {
    'academic': 'blue',
    'accounting': 'emerald',
    'operations': 'orange',
    'admin': 'purple',
}

BLUEPRINT_MODULE_CODES = {
    'students': 'students',
    'classes': 'classes',
    'exams': 'exams',
    'attendance': 'attendance',
    'fees': 'fees',
    'finance': 'finance',
    'inventory': 'inventory_uniform',
    'procurement': 'procurement_assets',
    'transport': 'fleet_transport',
    'farm': 'farm_operations',
}

PATH_PREFIX_MODULE_CODES = (
    ('/admin/fees', 'fees'),
    ('/fees/', 'fees'),
    ('/admin/finance', 'finance'),
    ('/admin/procurement', 'procurement_assets'),
    ('/fleet/', 'fleet_transport'),
    ('/fuel/', 'fleet_transport'),
    ('/issue_uniform', 'inventory_uniform'),
    ('/submit_issuance', 'inventory_uniform'),
    ('/manage_uniform_items', 'inventory_uniform'),
    ('/manage_stock', 'inventory_uniform'),
    ('/stock_', 'inventory_uniform'),
    ('/receipt/', 'inventory_uniform'),
    ('/print_receipt/', 'inventory_uniform'),
    ('/print_stock_levels', 'inventory_uniform'),
    ('/reports/', 'inventory_uniform'),
    ('/admin/term_dates', 'inventory_uniform'),
    ('/admin/add_uniform_item', 'inventory_uniform'),
    ('/admin/delete_uniform_item', 'inventory_uniform'),
    ('/admin/manage_classes', 'classes'),
    ('/admin/classes', 'classes'),
    ('/admin/class/', 'classes'),
    ('/admin/class_', 'classes'),
    ('/admin/get-classes-by-year', 'classes'),
    ('/admin/get-teachers', 'classes'),
    ('/api/class/', 'classes'),
    ('/admin/exams', 'exams'),
    ('/admin/grading-scales', 'exams'),
    ('/api/exams/', 'exams'),
    ('/attendance', 'attendance'),
    ('/farm/', 'farm_operations'),
    ('/admit', 'students'),
    ('/students', 'students'),
    ('/student/', 'students'),
    ('/print_admission_form/', 'students'),
    ('/api/search_parents', 'students'),
    ('/api/search_students', 'students'),
)

MODULE_REGISTRY_BY_CODE = {item['code']: item for item in MODULE_CATALOG}
MODULE_LABELS = {code: item['name'] for code, item in MODULE_REGISTRY_BY_CODE.items()}


def bundle_family_options():
    return BUNDLE_FAMILY_OPTIONS


def module_catalog_seed():
    return MODULE_CATALOG


def default_module_codes_for_bundle(bundle_family):
    return list(DEFAULT_BUNDLE_MODULE_CODES.get(bundle_family, []))


def module_definition(code):
    return MODULE_REGISTRY_BY_CODE.get(code)


def module_label(code):
    item = module_definition(code)
    if item:
        return item['name']
    return code.replace('_', ' ').title() if code else None


def family_label(code):
    return MODULE_FAMILY_LABELS.get(code, code.title() if code else None)


def family_color(code):
    return MODULE_FAMILY_COLORS.get(code, 'gray')


def module_group_label(code):
    item = module_definition(code)
    if item is None:
        return None
    if item.get('is_addon'):
        return 'Add-On'
    return 'Core'


def blueprint_module_codes():
    return BLUEPRINT_MODULE_CODES


def path_prefix_module_codes():
    return PATH_PREFIX_MODULE_CODES


def entitlement_filter_options():
    return [
        (item['code'], item['name'])
        for item in sorted(MODULE_CATALOG, key=lambda entry: (entry['sort_order'], entry['name']))
    ]