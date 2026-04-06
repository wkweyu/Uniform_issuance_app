from sqlalchemy import inspect, text

from extensions import db
from ..config.modules import bundle_family_options as module_bundle_family_options
from ..config.modules import default_module_codes_for_bundle as registry_default_module_codes_for_bundle
from ..config.modules import module_catalog_seed

from ..models import ModuleCatalog, Plan, PlanBandPrice, StudentBand

STUDENT_BAND_SEED = (
    {'label': '1-300', 'min_students': 1, 'max_students': 300, 'sort_order': 10},
    {'label': '301-700', 'min_students': 301, 'max_students': 700, 'sort_order': 20},
    {'label': '701-1500', 'min_students': 701, 'max_students': 1500, 'sort_order': 30},
    {'label': '1500+', 'min_students': 1501, 'max_students': None, 'sort_order': 40},
)


def bundle_family_options():
    return module_bundle_family_options()


def _ensure_plan_columns(engine):
    inspector = inspect(engine)
    if not inspector.has_table('plans'):
        return

    existing_columns = {column['name'] for column in inspector.get_columns('plans')}
    statements = []
    if 'bundle_family' not in existing_columns:
        statements.append("ALTER TABLE plans ADD COLUMN bundle_family VARCHAR(32) NOT NULL DEFAULT 'combined'")
    if 'pricing_model' not in existing_columns:
        statements.append("ALTER TABLE plans ADD COLUMN pricing_model VARCHAR(32) NOT NULL DEFAULT 'student_band'")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _ensure_pricing_tables(engine):
    bind = engine
    ModuleCatalog.__table__.create(bind=bind, checkfirst=True)
    StudentBand.__table__.create(bind=bind, checkfirst=True)
    from ..models import PlanModule, PlanBandPrice

    PlanModule.__table__.create(bind=bind, checkfirst=True)
    PlanBandPrice.__table__.create(bind=bind, checkfirst=True)


def _seed_legacy_plan_band_prices(db_session):
    student_bands = StudentBand.query.order_by(StudentBand.sort_order.asc()).all()
    if not student_bands:
        return

    existing_plan_ids = {row.plan_id for row in PlanBandPrice.query.with_entities(PlanBandPrice.plan_id).distinct().all()}
    legacy_plans = Plan.query.filter(~Plan.id.in_(existing_plan_ids)).all() if existing_plan_ids else Plan.query.all()
    for plan in legacy_plans:
        for band in student_bands:
            db_session.add(
                PlanBandPrice(
                    plan_id=plan.id,
                    student_band_id=band.id,
                    price_cents=plan.price_cents or 0,
                )
            )


def ensure_pricing_catalog_seeded(db_session):
    engine = db_session.get_bind() or db.engine
    _ensure_plan_columns(engine)
    _ensure_pricing_tables(engine)

    existing_module_codes = {row.code for row in ModuleCatalog.query.all()}
    for item in module_catalog_seed():
        if item['code'] in existing_module_codes:
            continue
        db_session.add(ModuleCatalog(**item))

    existing_band_labels = {row.label for row in StudentBand.query.all()}
    for item in STUDENT_BAND_SEED:
        if item['label'] in existing_band_labels:
            continue
        db_session.add(StudentBand(**item))

    db_session.flush()
    _seed_legacy_plan_band_prices(db_session)

    db_session.commit()


def default_module_codes_for_bundle(bundle_family):
    return registry_default_module_codes_for_bundle(bundle_family)


def pricing_features_snapshot(bundle_family, selected_modules, band_prices, student_bands):
    return {
        'pricing_model': 'student_band',
        'bundle_family': bundle_family,
        'modules': selected_modules,
        'band_prices': {
            band.label: band_prices.get(band.id, 0)
            for band in student_bands
        },
    }