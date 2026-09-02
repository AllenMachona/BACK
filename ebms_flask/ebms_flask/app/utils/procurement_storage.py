import re


def procurement_folder_name(procurement):
    """Return one readable, filesystem-safe folder name for a procurement."""
    title = _clean_component(procurement.title)
    tender_number = _clean_component(procurement.tender_number)
    folder_name = f'{title} - {tender_number}'
    return folder_name[:180].rstrip(' .') or f'procurement-{procurement.id}'


def _clean_component(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', str(value or ''))
    value = re.sub(r'\s+', ' ', value).strip(' .')
    return value
