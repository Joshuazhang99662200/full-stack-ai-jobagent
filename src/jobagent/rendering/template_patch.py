"""Preserve a Word package while replacing explicitly permitted prose and bold.

This does not approve facts or certify pagination. Its output still needs the
independent claim review and same-renderer PDF layout comparison before delivery.
"""

import hashlib
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile

from jobagent.schemas.template_tailoring import TemplatePatch

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML = "{http://www.w3.org/XML/1998/namespace}"


def patch_template(
    source: Path, output: Path, plan: TemplatePatch, *, allowed_paragraphs: set[int],
) -> None:
    """Write a separate copy; reject drift, control characters and growth upfront."""
    from lxml import etree  # type: ignore[import-untyped]

    if source.resolve() == output.resolve():
        raise ValueError("The retained template must never be overwritten.")
    if hashlib.sha256(source.read_bytes()).hexdigest() != plan.template_sha256:
        raise ValueError("Template digest changed; review the source again.")
    with ZipFile(source) as original:
        document = etree.fromstring(
            original.read("word/document.xml"),
            parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
        paragraphs = list(document.iter(W + "p"))
        for edit in plan.edits:
            index = edit.paragraph_index
            if index not in allowed_paragraphs or index >= len(paragraphs):
                raise ValueError("Paragraph is outside the permitted body slots.")
            paragraph = paragraphs[index]
            # Only w:t values count: properties and markup are not candidate prose.
            text = "".join(t.text or "" for t in paragraph.iter(W + "t"))
            replacement = "".join(run.text for run in edit.runs)
            if text != edit.expected_text:
                raise ValueError("Original paragraph text changed.")
            if len(replacement) > len(text):
                raise ValueError("Text exceeds its source slot budget; shorten the wording.")
            if any(c in replacement for c in ("\n", "\r", "\t", "\x00")):
                raise ValueError("Only prose and bold may change, not layout controls.")
            if any(child.tag not in (W + "pPr", W + "r") for child in paragraph):
                raise ValueError("Complex paragraphs need a separate explicit adapter.")
            old_runs = list(paragraph.findall(W + "r"))
            if any(child.tag not in (W + "rPr", W + "t")
                   for run in old_runs for child in run):
                raise ValueError("Do not replace fields, tabs, drawings or breaks.")
            if edit.run_edits:
                rewritten = ["".join(t.text or "" for t in r.iter(W + "t")) for r in old_runs]
                for change in edit.run_edits:
                    if (change.run_index >= len(old_runs)
                            or rewritten[change.run_index] != change.expected_text
                            or len(old_runs[change.run_index].findall(W + "t")) != 1):
                        raise ValueError("Original source run changed or is not a plain text slot.")
                    rewritten[change.run_index] = change.text
                replacement = "".join(rewritten)
                if len(replacement) > len(text) or any(
                    c in replacement for c in ("\n", "\r", "\t", "\x00")
                ):
                    raise ValueError("Source-run edits exceed the prose slot budget.")
                for change in edit.run_edits:
                    node = old_runs[change.run_index].find(W + "t")
                    node.text = change.text
                    node.set(XML + "space", "preserve")
                continue
            properties = old_runs[0].find(W + "rPr") if old_runs else None
            non_bold_formats = set()
            for old_run in old_runs:
                old_properties = old_run.find(W + "rPr")
                signature = () if old_properties is None else tuple(
                    etree.tostring(child, method="c14n") for child in old_properties
                    if child.tag not in (W + "b", W + "bCs")
                )
                non_bold_formats.add(signature)
            if len(non_bold_formats) > 1:
                raise ValueError("Mixed non-bold formatting needs an explicit slot adapter.")
            for run in old_runs:
                paragraph.remove(run)
            for segment in edit.runs:
                run = etree.SubElement(paragraph, W + "r")
                props = deepcopy(properties) if properties is not None else etree.Element(W + "rPr")
                for tag in ("b", "bCs"):
                    for node in props.findall(W + tag):
                        props.remove(node)
                    node = etree.SubElement(props, W + tag)
                    node.set(W + "val", "1" if segment.bold else "0")
                run.append(props)
                text_node = etree.SubElement(run, W + "t")
                text_node.set(XML + "space", "preserve")
                text_node.text = segment.text
        xml = etree.tostring(document, xml_declaration=True, encoding="UTF-8", standalone=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(output, "w") as tailored:
            for member in original.infolist():
                tailored.writestr(
                    member, xml if member.filename == "word/document.xml"
                    else original.read(member.filename),
                )
