# -*- coding: utf-8 -*-
"""
migrator_core.analyzers.dependency_analyzer
===========================================
Constructs element dependency graphs and performs topological sorting
to ensure hosts are created prior to hosted elements.
"""

from ..constants import Phase

HOST_CATEGORIES = {
    "Walls", "Floors", "Roofs", "Ceilings",
    "Structural Columns", "Structural Framing"
}

HOSTED_CATEGORIES = {
    "Doors", "Windows", "Openings"
}

MEP_CATEGORIES = {
    "Pipes", "Ducts", "Cable Trays", "Conduits",
    "Pipe Fittings", "Duct Fittings", "Cable Tray Fittings"
}

class DependencyAnalyzer(object):
    """
    Sorts elements so that host elements precede hosted elements,
    and MEP runs precede fittings.
    """

    @classmethod
    def get_phase_for_element(cls, element_record):
        cat = element_record.category_name
        if cat in HOST_CATEGORIES:
            return Phase.HOSTS
        elif cat in HOSTED_CATEGORIES or element_record.host_unique_id:
            return Phase.HOSTED
        elif cat in MEP_CATEGORIES:
            return Phase.MEP
        elif cat in ("Rooms", "Spaces", "Areas"):
            return Phase.SPECIAL
        return Phase.HOSTED

    @classmethod
    def sort_elements(cls, elements):
        """
        Topologically sorts elements based on phase priority and host relationships.
        """
        # Index elements by unique_id
        elem_map = {}
        for el in elements:
            if el.source_unique_id:
                elem_map[el.source_unique_id] = el

        # Group by phase
        phase_groups = {}
        for el in elements:
            p = cls.get_phase_for_element(el)
            if p not in phase_groups:
                phase_groups[p] = []
            phase_groups[p].append(el)

        sorted_result = []

        for p_idx in sorted(phase_groups.keys()):
            sub_list = phase_groups[p_idx]
            # If hosted phase, sort topologically based on host_unique_id
            if p_idx == Phase.HOSTED:
                sorted_hosted = cls._topological_sort_hosted(sub_list, elem_map)
                sorted_result.extend(sorted_hosted)
            else:
                sorted_result.extend(sub_list)

        return sorted_result

    @classmethod
    def _topological_sort_hosted(cls, hosted_elements, all_elements_map):
        """
        Ensures if A is hosted on B, B comes before A.
        Handles cycles gracefully.
        """
        result = []
        visited = set()
        in_stack = set()

        def visit(el):
            uid = el.source_unique_id
            if uid in in_stack:
                # Cycle detected, break cycle
                return
            if uid in visited:
                return

            in_stack.add(uid)

            # Check if host exists in this sub-list
            host_uid = el.host_unique_id
            if host_uid and host_uid in all_elements_map:
                host_elem = all_elements_map[host_uid]
                # If host is in hosted group, visit host first
                if host_elem in hosted_elements:
                    visit(host_elem)

            in_stack.remove(uid)
            visited.add(uid)
            result.append(el)

        for el in hosted_elements:
            if el.source_unique_id not in visited:
                visit(el)

        return result
