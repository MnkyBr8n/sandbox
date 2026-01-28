# sandbox/app/extraction/field_mapper.py
"""
Purpose: Map parser outputs into 12 categorized snapshot types.

Architecture:
- Accepts dict outputs from parsers (field_id → value mapping)
- Categorizes fields into 12 snapshot types
- Returns categorized field map for snapshot builder
- Merges outputs from multiple parsers (tree_sitter + semgrep)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any

from app.logging.logger import get_logger


class FieldMappingError(Exception):
    pass


# 12 snippet categories mapping
SNIPPET_CATEGORIES = {
    "file_metadata": [
        "code.file.path",
        "code.file.language",
        "code.file.loc",
        "code.file.package"
    ],
    "imports": [
        "code.imports.modules",
        "code.imports.from_files",
        "code.imports.external",
        "code.imports.internal"
    ],
    "exports": [
        "code.exports.functions",
        "code.exports.classes",
        "code.exports.constants",
        "code.exports.types"
    ],
    "functions": [
        "code.functions.names",
        "code.functions.signatures",
        "code.functions.async",
        "code.functions.decorators"
    ],
    "classes": [
        "code.classes.names",
        "code.classes.inheritance",
        "code.classes.methods",
        "code.classes.properties",
        "code.classes.interfaces"
    ],
    "connections": [
        "code.connections.depends_on",
        "code.connections.depended_by",
        "code.connections.function_calls",
        "code.connections.instantiates"
    ],
    "repo_metadata": [
        "repo.primary_language",
        "repo.entrypoints",
        "repo.modules",
        "repo.test_framework",
        "repo.ci_pipeline"
    ],
    "security": [
        "code.security.vulnerabilities",
        "code.security.hardcoded_secrets",
        "code.security.sql_injection_risks",
        "code.security.xss_risks"
    ],
    "quality": [
        "code.quality.antipatterns",
        "code.quality.code_smells",
        "code.quality.todos",
        "code.quality.deprecated_usage"
    ],
    "doc_metadata": [
        "doc.title",
        "doc.author",
        "doc.date",
        "doc.version",
        "doc.language"
    ],
    "doc_content": [
        "doc.summary",
        "doc.key_concepts",
        "doc.technical_terms",
        "doc.acronyms",
        "doc.urls",
        "doc.code_snippets"
    ],
    "doc_analysis": [
        "doc.key_requirements",
        "doc.entities",
        "doc.references",
        "doc.related_files",
        "doc.api_endpoints",
        "doc.open_questions",
        "doc.risks",
        "doc.decisions",
        "doc.assumptions",
        "doc.constraints"
    ]
}

# Reverse mapping: field_id → snippet_type
FIELD_TO_SNIPPET_TYPE = {}
for snippet_type, field_ids in SNIPPET_CATEGORIES.items():
    for field_id in field_ids:
        FIELD_TO_SNIPPET_TYPE[field_id] = snippet_type


@dataclass
class CategorizedFields:
    """Field map categorized by snippet type."""
    snippets: Dict[str, Dict[str, Any]]  # snippet_type → {field_id: value}
    parser: str  # Parser that generated these fields


class FieldMapper:
    def __init__(self, *, master_schema: Dict[str, Any]) -> None:
        """
        Args:
            master_schema: Loaded master_notebook.yaml
        """
        self.master_schema = master_schema
        self.logger = get_logger("extraction.field_mapper")
        
        # Build allowed field set from schema
        self.allowed_field_ids = self._build_allowed_fields()
    
    def _build_allowed_fields(self) -> set:
        """Extract all allowed field_ids from master schema."""
        allowed = set()
        field_registry = self.master_schema.get("field_id_registry", {})
        
        for category, fields in field_registry.items():
            for field_def in fields:
                allowed.add(field_def["field_id"])
        
        return allowed
    
    def categorize_parser_output(
        self,
        parser_output: Dict[str, Any],
        parser_name: str,
        source_file: str
    ) -> CategorizedFields:
        """
        Categorize parser output dict into 12 snippet types.
        
        Args:
            parser_output: Dict with field_id → value mappings from parser
            parser_name: Name of parser (tree_sitter, semgrep, text_extractor, csv_parser)
            source_file: Source file path
        
        Returns:
            CategorizedFields with snippets organized by type
        """
        categorized = {snippet_type: {} for snippet_type in SNIPPET_CATEGORIES.keys()}
        unknown_fields = []
        
        for field_id, value in parser_output.items():
            # Validate field_id
            if field_id not in self.allowed_field_ids:
                unknown_fields.append(field_id)
                self.logger.warning(f"Unknown field_id from {parser_name}: {field_id}")
                continue
            
            # Get snippet type for this field
            snippet_type = FIELD_TO_SNIPPET_TYPE.get(field_id)
            
            if snippet_type is None:
                self.logger.warning(f"Field {field_id} not mapped to any snippet type")
                continue
            
            # Add to appropriate snippet category
            categorized[snippet_type][field_id] = value
        
        # Remove empty snippet categories
        categorized = {k: v for k, v in categorized.items() if v}
        
        self.logger.info("Categorized parser output", extra={
            "parser": parser_name,
            "source_file": source_file,
            "total_fields": len(parser_output),
            "snippet_types_created": len(categorized),
            "unknown_fields": len(unknown_fields)
        })
        
        return CategorizedFields(snippets=categorized, parser=parser_name)
    
    def merge_categorized_fields(
        self,
        *categorized_list: CategorizedFields
    ) -> Dict[str, Dict[str, Any]]:
        """
        Merge multiple CategorizedFields (from different parsers) into single dict.
        
        Args:
            *categorized_list: Multiple CategorizedFields from different parsers
        
        Returns:
            Merged dict: snippet_type → {field_id: value}
        """
        merged = {snippet_type: {} for snippet_type in SNIPPET_CATEGORIES.keys()}
        
        for categorized in categorized_list:
            for snippet_type, fields in categorized.snippets.items():
                # Merge fields, later values overwrite earlier
                merged[snippet_type].update(fields)
        
        # Remove empty snippet categories
        merged = {k: v for k, v in merged.items() if v}
        
        self.logger.info("Merged categorized fields", extra={
            "parsers_merged": len(categorized_list),
            "snippet_types_total": len(merged)
        })
        
        return merged
