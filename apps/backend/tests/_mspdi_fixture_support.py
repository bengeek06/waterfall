"""Le jeu de données MS Project des tests : fixtures versionnées et générateur de volume.

Deliberately not named ``test_*.py`` (same reasoning as ``_calendar_support.py``):
pytest would otherwise collect it as a test module.

Pourquoi ce module existe
-------------------------

Un test qui a besoin d'un planning à importer a trois mauvaises façons de s'en
procurer un : recomposer une chaîne XML dans son propre corps (illisible et
jamais réutilisé), pointer un fichier hors du dépôt (vert en local, rouge en
CI — c'est exactement ce qui a cassé la CI depuis #328), ou committer un gros
fichier (des minutes de parsing à chaque exécution). Ce module donne la
quatrième : de **petites fixtures versionnées, chacune ciblant une forme
précise**, et un **générateur** pour tout ce qui relève du volume.

Aucune de ces données ne vient d'un planning client. Le répertoire de plannings
réels que le ``.gitignore`` exclut dès sa première ligne le reste : rien n'en est
lu, copié ni dérivé ici, pas même un sous-ensemble anonymisé.

Comment s'en servir
-------------------

Pour une forme précise, prendre la fixture qui la porte et l'envoyer telle
quelle à l'import (API ou service) ::

    from _mspdi_fixture_support import HIERARCHY_MSPDI, mspdi_bytes

    response = import_xml(client, headers, project_id, mspdi_bytes(HIERARCHY_MSPDI))

Pour raisonner sur l'arbre sans passer par la base, lire la fixture en
structures neutres — ni ORM, ni domaine, juste des dataclasses ::

    planning = read_mspdi(mspdi_bytes(MILESTONES_MSPDI))
    assert planning.milestone_uids() == (3, 5, 7)

Pour un test de charge, **ne pas** committer de fichier : générer ::

    xml = generate_mspdi(task_count=240, depth=4, milestone_every=5, link_every=3)

Le domaine a son propre banc au-dessus de tout ceci
(``_revision_domain_support.build_planning_bench``), qui prend le
:class:`MspdiPlanning` renvoyé par :func:`read_mspdi` et en fait une révision
brouillon peuplée.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

#: MSPDI namespace des fixtures. Les deux namespaces MS Project sont acceptés à
#: l'import ; celui-ci (``/2007``) est en plus validé contre le XSD canonique,
#: donc une fixture malformée est refusée par le parseur avant d'atteindre un test.
MSPDI_NAMESPACE = "http://schemas.microsoft.com/project/2007"
_NS = f"{{{MSPDI_NAMESPACE}}}"

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

#: Hiérarchie sur 4 niveaux avec récapitulatifs (14 tâches).
HIERARCHY_MSPDI = FIXTURES_DIR / "mspdi_hierarchy.xml"
#: Jalons sous un récapitulatif et à la racine (7 tâches, 3 jalons).
MILESTONES_MSPDI = FIXTURES_DIR / "mspdi_milestones.xml"
#: Liens des quatre types MSPDI, décalages positif et négatif (7 tâches, 5 liens).
LINKS_WITH_LAG_MSPDI = FIXTURES_DIR / "mspdi_links_with_lag.xml"
#: Dates, durées, avancement et un bloc ``<Calendars>`` ignoré à l'import (4 tâches).
SCHEDULE_CALENDAR_MSPDI = FIXTURES_DIR / "mspdi_schedule_calendar.xml"

#: Toutes les fixtures, pour un test paramétré qui doit valoir sur chacune.
ALL_MSPDI_FIXTURES = (
    HIERARCHY_MSPDI,
    MILESTONES_MSPDI,
    LINKS_WITH_LAG_MSPDI,
    SCHEDULE_CALENDAR_MSPDI,
)


def mspdi_bytes(path: Path) -> bytes:
    """Contenu d'une fixture, prêt à être posté sur ``/imports/v1/batches/{id}/xml``."""
    return path.read_bytes()


# --------------------------------------------------------------------------------------
# Lecture : du XML vers des structures neutres
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MspdiTask:
    """Une tâche du fichier, son parent déjà résolu depuis l'``OutlineLevel``."""

    uid: int
    name: str
    parent_uid: int | None
    outline_level: int
    duration_minutes: int | None
    is_summary: bool
    is_milestone: bool
    percent_complete: int


@dataclass(frozen=True)
class MspdiLink:
    """Un lien de précédence ``predecessor_uid -> uid``, type et décalage compris."""

    uid: int
    predecessor_uid: int
    link_type: int
    lag_tenth_minute: int
    lag_format: int | None


@dataclass(frozen=True)
class MspdiPlanning:
    """Un planning lu, dans l'ordre du fichier."""

    tasks: list[MspdiTask] = field(default_factory=list)
    links: list[MspdiLink] = field(default_factory=list)

    def uids(self) -> tuple[int, ...]:
        return tuple(task.uid for task in self.tasks)

    def milestone_uids(self) -> tuple[int, ...]:
        return tuple(task.uid for task in self.tasks if task.is_milestone)

    def leaf_uids(self) -> tuple[int, ...]:
        """Uids des tâches qui ne portent aucun enfant, dans l'ordre du fichier."""
        parents = {task.parent_uid for task in self.tasks}
        return tuple(task.uid for task in self.tasks if task.uid not in parents)

    def max_outline_level(self) -> int:
        return max((task.outline_level for task in self.tasks), default=0)

    def predecessor_pairs(self) -> list[tuple[int, int]]:
        """``(uid, predecessor_uid)``, la forme qu'attend le banc de domaine."""
        return [(link.uid, link.predecessor_uid) for link in self.links]


def _text(node: ElementTree.Element, tag: str) -> str:
    return node.findtext(_NS + tag) or ""


def _integer(node: ElementTree.Element, tag: str, default: int = 0) -> int:
    raw = _text(node, tag)
    return int(raw) if raw else default


def _optional_integer(node: ElementTree.Element, tag: str) -> int | None:
    raw = _text(node, tag)
    return int(raw) if raw else None


def _duration_minutes(raw: str) -> int | None:
    """``PT960M`` -> 960. Seule la forme que ce module écrit est reconnue."""
    if not raw.startswith("PT") or not raw.endswith("M"):
        return None
    body = raw[2:-1]
    return int(body) if body.isdigit() else None


def read_mspdi(xml: bytes) -> MspdiPlanning:
    """Lire un document MSPDI en structures neutres, parent déjà résolu.

    Le parent d'une tâche est la tâche la plus proche au-dessus d'elle dont
    l'``OutlineLevel`` vaut un de moins — l'ordre que MS Project écrit lui-même.
    La ligne récapitulative de projet (UID 0, niveau 0) n'est pas une tâche du
    projet et est ignorée, comme le fait ``services.msproject_xml``.

    Volontairement indépendant de ``waterfall.services.msproject_xml`` : les
    tests de domaine se servent de cette lecture, et le domaine ne doit rien
    connaître de MS Project, pas même à travers son banc d'essai.
    """
    root = ElementTree.fromstring(xml)
    container = root.find(_NS + "Tasks")
    if container is None:
        return MspdiPlanning()

    tasks: list[MspdiTask] = []
    links: list[MspdiLink] = []
    open_parents: dict[int, int] = {}
    for entry in container:
        uid = _integer(entry, "UID")
        level = _integer(entry, "OutlineLevel")
        if uid == 0 and level == 0:
            continue
        open_parents[level] = uid
        tasks.append(
            MspdiTask(
                uid=uid,
                name=_text(entry, "Name"),
                parent_uid=open_parents.get(level - 1) if level > 1 else None,
                outline_level=level,
                duration_minutes=_duration_minutes(_text(entry, "Duration")),
                is_summary=_text(entry, "Summary") == "1",
                is_milestone=_text(entry, "Milestone") == "1",
                percent_complete=_integer(entry, "PercentComplete"),
            )
        )
        links.extend(
            MspdiLink(
                uid=uid,
                predecessor_uid=_integer(predecessor, "PredecessorUID"),
                link_type=_integer(predecessor, "Type", 1),
                lag_tenth_minute=_integer(predecessor, "LinkLag"),
                lag_format=_optional_integer(predecessor, "LagFormat"),
            )
            for predecessor in entry.findall(_NS + "PredecessorLink")
        )
    return MspdiPlanning(tasks=tasks, links=links)


def read_mspdi_fixture(path: Path) -> MspdiPlanning:
    """Raccourci ``read_mspdi(mspdi_bytes(path))``."""
    return read_mspdi(mspdi_bytes(path))


# --------------------------------------------------------------------------------------
# Écriture : le générateur de volume
# --------------------------------------------------------------------------------------

#: Libellé par niveau d'indentation, pour que le nom dise où la tâche se trouve.
_LEVEL_LABELS = ("Lot", "Sous-ensemble", "Phase", "Activité", "Opération", "Tâche")


def _outline_levels(task_count: int, depth: int, branching: int) -> list[int]:
    """Niveaux d'indentation, en ordre de parcours préfixe, d'un arbre équilibré.

    Chaque tâche non feuille reçoit ``branching`` enfants jusqu'à épuisement du
    quota ``task_count`` ; de nouvelles racines sont ouvertes tant qu'il en
    reste. La suite renvoyée ne progresse jamais de plus d'un niveau à la fois,
    ce qu'exige la numérotation hiérarchique de MS Project.
    """
    levels: list[int] = []

    def emit(level: int) -> None:
        if len(levels) >= task_count:
            return
        levels.append(level)
        if level < depth:
            for _ in range(branching):
                emit(level + 1)

    while len(levels) < task_count:
        emit(1)
    return levels


def _scattered_uids(count: int) -> list[int]:
    """UID épars et non triés, comme un vrai fichier édité plusieurs fois en porte.

    MS Project n'attribue pas les UID dans l'ordre du document et ne les
    renumérote pas après une suppression : un planning réel de 542 tâches monte
    couramment jusqu'à 718 et n'est pas trié. Un générateur qui émettrait
    ``1..n`` laisserait passer un code qui confond l'``external_uid`` avec le rang
    de la ligne — exactement ce que la clé d'identité du modèle de révision
    interdit. La dispersion est déterministe : un pas de 3, puis une transposition
    des paires voisines.
    """
    uids = [1 + index * 3 for index in range(count)]
    for index in range(0, count - 1, 2):
        uids[index], uids[index + 1] = uids[index + 1], uids[index]
    return uids


def _outline_numbers(levels: list[int]) -> list[str]:
    numbers: list[str] = []
    counters: list[int] = []
    for level in levels:
        if level > len(counters):
            counters.append(1)
        else:
            del counters[level:]
            counters[level - 1] += 1
        numbers.append(".".join(str(counter) for counter in counters))
    return numbers


#: Types et décalages parcourus cycliquement par les liens générés. Un planning
#: réel n'est pas fait que de fin-à-début à décalage nul, et un générateur qui
#: n'en produirait que laisserait passer une perte de type ou de lag sans bruit.
#: ``(1=FS, 2=SS, 0=FF, 3=SF)``, décalages en dixièmes de minute.
_LINK_TYPE_CYCLE = (1, 1, 2, 0, 3)
_LINK_LAG_CYCLE = (0, 4800, -2400, 0, 9600)


def _task_element(
    *,
    uid: int,
    name: str,
    outline: str,
    level: int,
    is_summary: bool,
    is_milestone: bool,
    duration_minutes: int,
    predecessor_uid: int | None,
    link_rank: int,
) -> str:
    predecessor = (
        ""
        if predecessor_uid is None
        else (
            "<PredecessorLink>"
            f"<PredecessorUID>{predecessor_uid}</PredecessorUID>"
            f"<Type>{_LINK_TYPE_CYCLE[link_rank % len(_LINK_TYPE_CYCLE)]}</Type>"
            f"<LinkLag>{_LINK_LAG_CYCLE[link_rank % len(_LINK_LAG_CYCLE)]}</LinkLag>"
            "<LagFormat>7</LagFormat>"
            "</PredecessorLink>"
        )
    )
    return (
        "<Task>"
        f"<UID>{uid}</UID><ID>{uid}</ID><Name>{escape(name)}</Name>"
        f"<Type>{1 if is_summary else 0}</Type>"
        f"<OutlineNumber>{outline}</OutlineNumber><OutlineLevel>{level}</OutlineLevel>"
        f"<Duration>PT{duration_minutes}M</Duration><DurationFormat>7</DurationFormat>"
        "<PercentComplete>0</PercentComplete>"
        f"<Summary>{1 if is_summary else 0}</Summary>"
        f"<Milestone>{1 if is_milestone else 0}</Milestone>"
        f"{predecessor}"
        "</Task>"
    )


def generate_mspdi(
    *,
    task_count: int,
    depth: int,
    branching: int = 4,
    milestone_every: int = 0,
    link_every: int = 0,
    scatter_uids: bool = True,
    name: str = "Planning synthétique",
    guid: str = "GENERATED-MSPDI-0001",
) -> bytes:
    """Un document MSPDI valide de ``task_count`` tâches réparties sur ``depth`` niveaux.

    C'est ce qui remplace un gros fichier committé : la propriété qu'un test de
    volume vérifie est que **l'arbre tient la charge et la profondeur**, pas
    qu'un fichier particulier s'importe. Le document est déterministe — mêmes
    paramètres, mêmes octets — donc un échec se rejoue tel quel.

    :param task_count: nombre exact de ``<Task>`` émises (hors ligne récapitulative
        de projet, que ce générateur n'écrit pas).
    :param depth: profondeur maximale atteinte ; la première branche y descend dès
        lors que ``task_count >= depth``.
    :param branching: nombre d'enfants d'une tâche non feuille. Avec la valeur par
        défaut, un récapitulatif a toujours plusieurs frères sous lui, ce dont ont
        besoin les opérations d'indentation et de déplacement.
    :param milestone_every: une feuille sur ``milestone_every`` devient un jalon
        (durée nulle). ``0`` n'en produit aucun.
    :param link_every: une feuille sur ``link_every`` reçoit un lien vers la feuille
        précédente, les types et décalages étant pris cycliquement dans
        :data:`_LINK_TYPE_CYCLE` / :data:`_LINK_LAG_CYCLE` — les quatre types MSPDI
        et des décalages positif, négatif et nul y passent. Le prédécesseur est
        toujours en amont dans l'ordre du fichier, donc le graphe reste acyclique
        (INV-18). ``0`` n'en produit aucun.
    :param scatter_uids: émettre des UID épars et non triés (voir
        :func:`_scattered_uids`) plutôt que ``1..task_count``. Par défaut oui,
        parce que c'est ce que produit MS Project ; ``False`` donne un fichier plus
        facile à lire à l'œil quand c'est le test lui-même qu'on met au point.
    :raises ValueError: si ``task_count``, ``depth`` ou ``branching`` est non positif.
    """
    if task_count < 1:
        raise ValueError("task_count must be >= 1")
    if depth < 1:
        raise ValueError("depth must be >= 1")
    if branching < 1:
        raise ValueError("branching must be >= 1")

    levels = _outline_levels(task_count, depth, branching)
    numbers = _outline_numbers(levels)
    # Une tâche est récapitulative si la suivante est un cran plus bas qu'elle.
    is_summary = [
        index + 1 < len(levels) and levels[index + 1] > level for index, level in enumerate(levels)
    ]

    uids = _scattered_uids(task_count) if scatter_uids else list(range(1, task_count + 1))
    tasks: list[str] = []
    leaf_rank = 0
    link_rank = 0
    previous_leaf_uid: int | None = None
    rows = zip(levels, numbers, is_summary, strict=True)
    for index, (level, outline, summary) in enumerate(rows):
        uid = uids[index]
        milestone = False
        predecessor_uid: int | None = None
        if not summary:
            leaf_rank += 1
            milestone = milestone_every > 0 and leaf_rank % milestone_every == 0
            if link_every > 0 and leaf_rank % link_every == 0:
                predecessor_uid = previous_leaf_uid
        label = _LEVEL_LABELS[min(level, len(_LEVEL_LABELS)) - 1]
        tasks.append(
            _task_element(
                uid=uid,
                name=f"Jalon {outline}" if milestone else f"{label} {outline}",
                outline=outline,
                level=level,
                is_summary=summary,
                is_milestone=milestone,
                # Récapitulative : MS Project en calcule la durée, on l'écrit à 0.
                duration_minutes=0 if (summary or milestone) else 480 * (1 + index % 5),
                predecessor_uid=predecessor_uid,
                link_rank=link_rank,
            )
        )
        if predecessor_uid is not None:
            link_rank += 1
        if not summary:
            previous_leaf_uid = uid

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Project xmlns="{MSPDI_NAMESPACE}">'
        f"<SaveVersion>16</SaveVersion><GUID>{escape(guid)}</GUID>"
        f"<Name>{escape(name)}</Name>"
        "<ScheduleFromStart>1</ScheduleFromStart>"
        "<StartDate>2026-01-05T08:00:00</StartDate>"
        "<FinishDate>2027-12-31T17:00:00</FinishDate>"
        "<MinutesPerDay>480</MinutesPerDay><MinutesPerWeek>2400</MinutesPerWeek>"
        "<DaysPerMonth>20</DaysPerMonth><CurrencyCode>EUR</CurrencyCode>"
        f"<Tasks>{''.join(tasks)}</Tasks>"
        "</Project>"
    ).encode()
