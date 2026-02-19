# SENAITE Full Parity Matrix (Working)

Source trees:
- senaite.lims: /Users/mingxingmac/Documents/Codex/senaite/senaite.lims
- senaite.core: /Users/mingxingmac/Documents/Codex/senaite/senaite.core

Target app:
- laboratory_management (Frappe/ERPNext)

## Status Legend
- DONE: Implemented + deployed + smoke-tested
- PARTIAL: Implemented partially
- TODO: Not implemented

## Core Domain Objects (SENAITE -> laboratory_management)

### Setup / Master Data
- Clients / Contacts / Persons: PARTIAL (LIMS Client exists; deeper contact model TODO)
- Departments: DONE (LIMS Department + optional ERPNext Department link)
- Sample Types: DONE
- Sample Points: DONE
- Sample Conditions / Preservations / Matrices / Containers / Container Types: DONE
- Analysis Categories: DONE
- Analysis Profiles / Sample Templates / Worksheet Templates: DONE (baseline)
- Interpretation Templates: DONE (basic) + TODO (full rule set parity)
- Dynamic Analysis Specifications: PARTIAL (Analysis Specification + enforcement on result capture)
- Storage Locations: PARTIAL (Storage Location exists; needs full tracking/stock parity)
- Lab Products / Suppliers / Manufacturers: TODO
- Labels / Sticker templates / batch labels: PARTIAL (Label Batch + PDF generation)
- Attachment types: TODO

### Operational Objects
- Samples + accessioning + stability + TAT: DONE (core) + PARTIAL (full logistics and containerization TODO)
- Worksheets + layouts: DONE (basic) + TODO (template/layout parity)
- Batches: DONE (basic)
- Instruments / Instrument Types / Locations: PARTIAL (instrument core + asset calibration link DONE; instrument types/locations TODO)
- Result entry + verification workflow: DONE
- Retest/Reject/Retract traceability: DONE (basic) + TODO (full audit/workflow parity)
- Results report / COA: PARTIAL (COA + revisioned Results Report implemented; needs full SENAITE report parity)

### Quality
- IQC (Westgard): DONE
- EQA / Proficiency Testing: PARTIAL (scoring + auto CAPA; rounds/sign-off TODO)

### Interfaces
- ASTM: PARTIAL (parsing/import exists; code mapping + queue/retry DONE; full connector/driver TODO)
- HL7: PARTIAL (parsing/import exists; code mapping + queue/retry DONE; ORM/ORU bidirectional TODO)
- Import/Export setup data: TODO

### Finance
- Billing/invoicing/payment/credit note linkage: DONE (native ERPNext)

### Security / Audit
- Role model: DONE (basic roles)
- Audit log: DONE
- Electronic signature: DONE (image/pdf signature) + TODO (full e-sign audit chain parity)

## Immediate Next Implementation Wave
1. Master data parity: sample containers/conditions/preservations/matrices, instrument types/locations, departments.
2. Analysis Profiles + Sample Templates + Worksheet Templates parity.
3. Labels/stickers/barcode printing and batch labels.
4. ResultsReport parity (multi-format, attachments, release/cancel, revision control).
5. Interface stack parity: message queue, mapping, retries, bidirectional HL7.
6. EQA full parity: multi-round, scoring matrices, CAPA, review workflow.
