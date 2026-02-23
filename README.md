# Laboratory Management (Odoo 19)

Laboratory management workflow implemented on Odoo:

- Analysis service catalog and panels
- Sample accessioning and lifecycle
- Analysis execution and worksheet batching
- Result verification and report release
- Portal request/report and AI interpretation functions

## Documentation

- `/docs/LIS_CONFIGURATION_AND_ROLE_SOP_TRILINGUAL.md` - full configuration and role SOP (CN/EN/TH)
- `/docs/DEVELOPMENT_GUIDE.md` - developer guide and architecture notes
- `/docs/API_REFERENCE_TRILINGUAL.md` - integration reference (CN/EN/TH)
- `/docs/EXTERNAL_API_GUIDE_TRILINGUAL.md` - external institution integration guide
- `/docs/openapi/external_api_v1.yaml` - OpenAPI for external REST endpoints
- `/docs/openapi/interface_api_v1.yaml` - OpenAPI for LIS/HIS channel endpoints

## Version Notes (19.0.2.0.22)

- Added dynamic form engine (`lab.dynamic.form*`) for service/panel-bound collection fields.
- Added lab-native patient and physician master data models.
- Added request attachment upload for portal, internal workbench, and external API.
- Improved clean install behavior for security/menu loading order.
