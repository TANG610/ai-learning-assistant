-- Track whether an assessment was generated from one document or the full knowledge base.
ALTER TABLE assessments ADD COLUMN source_document_ids TEXT DEFAULT '';
ALTER TABLE assessments ADD COLUMN scope_label TEXT DEFAULT '';
