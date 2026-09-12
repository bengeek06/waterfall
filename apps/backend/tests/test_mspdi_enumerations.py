"""The MSPDI enumerations of the write payloads, re-derived from the bundled XSD.

``MspdiLagFormat`` and ``MspdiDurationFormat`` (``schemas/revisions.py``) restate, as
a Python ``Literal``, a list that lives in this repository already:
``resources/msproject-schemas/2016/tasks_2016_schema.xml``. Any restatement drifts,
and this one did -- the review of #331 (M1) found ``LagFormat`` short of its value 53,
because the original enumeration had been transcribed from the ``xsd:documentation``
of the element ("... 51=%? and 52=e%?") rather than from the ``xsd:enumeration`` list
underneath it, which descends to 53. The prose of ``DurationFormat``, which does
mention 53, is why only one of the two was wrong and why the mistake was invisible
next to its correct neighbour.

So this module does not restate the values a third time: it **parses the XSD** and
asserts the two ``Literal``s are exactly what it says. Add a value to either alias, or
drop one, and the test fails without anyone having to notice; swap the bundled schema
for a later MSPDI version and it reports precisely which codes moved.

The consequence of being wrong is a 422 on a file MS Project considers valid: an
import (#332) stores the code it read, ``GET .../nodes`` returns it, and the client
that sends the list back is refused -- see
``test_revision_planning_api.test_a_lag_format_the_mspdi_schema_allows_survives_a_read_modify_write``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import get_args

from waterfall.schemas.projects import MspdiLagFormat as LegacyMspdiLagFormat
from waterfall.schemas.revisions import MspdiDurationFormat, MspdiLagFormat

_XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema"
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "msproject-schemas"
    / "2016"
    / "tasks_2016_schema.xml"
)


def _schema_root() -> ElementTree.Element:
    """The bundled schema, parseable.

    The file is an *excerpt* of the MSPDI schema as Microsoft publishes it -- it opens
    on an XML declaration, then a literal ``. . .`` standing for the part that was cut,
    and it never declares the ``xsd`` prefix it uses throughout. So it is not a
    well-formed document and ``ElementTree.parse`` refuses it outright. Dropping the
    declaration and wrapping the rest in an element that binds the prefix makes it one,
    without touching the bundled file: the ``. . .`` becomes text of the wrapper, and
    every ``xsd:`` element below resolves. Structural parsing is worth that much
    ceremony -- a line-oriented regex over the whole file would have to guess where one
    ``<xsd:element>`` ends and the next begins, which is exactly the kind of guess that
    let 53 go missing.
    """
    source = _SCHEMA_PATH.read_text(encoding="utf-8")
    body = re.sub(r"^\s*<\?xml[^>]*\?>", "", source, count=1)
    return ElementTree.fromstring(f'<root xmlns:xsd="{_XSD_NAMESPACE}">{body}</root>')


def _enumerations_of(element_name: str) -> set[int]:
    """The ``xsd:enumeration`` values of ``<element_name>``, from the bundled schema.

    ``DurationFormat`` appears three times in the file (the task, and the two nested
    contexts that repeat it); the values are asserted identical rather than merged, so
    a schema where they diverged would be reported here instead of quietly unioned.
    """
    root = _schema_root()
    occurrences: list[set[int]] = []
    for element in root.iter(f"{{{_XSD_NAMESPACE}}}element"):
        if element.get("name") != element_name:
            continue
        values = {
            int(value)
            for enumeration in element.iter(f"{{{_XSD_NAMESPACE}}}enumeration")
            if (value := enumeration.get("value")) is not None
        }
        if values:
            occurrences.append(values)

    assert occurrences, f"no <{element_name}> with an enumeration in {_SCHEMA_PATH.name}"
    assert all(values == occurrences[0] for values in occurrences), (
        f"<{element_name}> declares different enumerations in different contexts"
    )
    return occurrences[0]


def test_the_lag_format_literal_is_the_enumeration_of_the_bundled_schema() -> None:
    assert set(get_args(MspdiLagFormat)) == _enumerations_of("LagFormat")


def test_the_duration_format_literal_is_the_enumeration_of_the_bundled_schema() -> None:
    assert set(get_args(MspdiDurationFormat)) == _enumerations_of("DurationFormat")


def test_the_two_enumerations_differ_by_the_single_value_duration_adds() -> None:
    """21 ("null") is the whole difference -- the reason one alias is not the other.

    Pinned because it is the sentence the comment above both aliases makes, and
    because a future divergence (a value added to one and forgotten in the other)
    would otherwise pass the two tests above while making the comment false.
    """
    duration = set(get_args(MspdiDurationFormat))
    lag = set(get_args(MspdiLagFormat))

    assert duration - lag == {21}
    assert lag - duration == set()


def test_the_legacy_task_link_payload_shares_the_same_literal() -> None:
    """#331 review, B1: one definition, imported twice, rather than two copies.

    ``schemas/projects.py`` carried its own transcription of ``LagFormat`` -- the one
    that was missing 53 -- and still serves live routes (``estimates``,
    ``planning_links``) until E14-12 (#339) removes them. It now imports the alias
    instead of restating it, which is what makes the three tests above cover both
    payloads. Identity, not equality: a second ``Literal`` with the same members today
    is exactly the situation that produced M1.
    """
    assert LegacyMspdiLagFormat is MspdiLagFormat
