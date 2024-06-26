import logging
import re
import requests_cache
from collections import defaultdict
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from tqdm import tqdm


from configs import configure_argument_parser, configure_logging
from constants import BASE_DIR, MAIN_DOC_URL, PEP_URL, EXPECTED_STATUS
from outputs import control_output
from utils import get_response, find_tag


def _output_mismatches_log(non_matching_statuses):
    """Выводит в лог сообщение с несовпадающими статусами."""
    message_log = ''
    if not non_matching_statuses:
        return
    for non_matching_status in non_matching_statuses:
        message_log += ('Несовпадающие статусы:\n'
                        f'{non_matching_status["url_detail"]}\n'
                        'Статус в карточке: '
                        f'{non_matching_status["status_detail"]}\n'
                        'Ожидаемые статусы: '
                        f'{non_matching_status["status_table"]}\n')
    logging.info(message_log)


def _forms_result_pep(count_status):
    """Формирует данные по парсинку PEP для вывода."""
    return [
        ('Статус', 'Количество'),
        *count_status.items(),
        ('Всего', sum(count_status.values())),
    ]


def pep(session):
    """Парсит статусы PEP."""
    response = get_response(session, PEP_URL)
    if response is None:
        return
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, features='lxml')
    section_pep_table = find_tag(soup, 'section',
                                 attrs={'id': 'numerical-index'})
    tbody_pep_table = find_tag(section_pep_table, 'tbody')
    tr_tags_pep_table = tbody_pep_table.find_all('tr')
    non_matching_statuses = []
    count_status = defaultdict(int)
    for tr_tag_pep_table in tqdm(tr_tags_pep_table):
        a_tag_pep_table = find_tag(tr_tag_pep_table, 'a', attrs={'class':
                                   'pep reference internal'})
        status_code = find_tag(tr_tag_pep_table, 'abbr').text[1:]
        status_table = EXPECTED_STATUS.get(status_code)
        url_pep_detail = urljoin(PEP_URL,
                                 a_tag_pep_table.get('href'))
        response = get_response(session, url_pep_detail)
        if response is None:
            return
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, features='lxml')
        dt_tags_pep_detail = soup.find_all('dt', {'class': 'field-even'})
        for dt_tag_pep_detail in dt_tags_pep_detail:
            is_status = dt_tag_pep_detail.find(string='Status')
            if is_status is None:
                continue
            dd_tag_pep_detail = dt_tag_pep_detail.find_next_sibling(
                'dd', {'class': 'field-even'}
                )
            status = dd_tag_pep_detail.text
            if status in EXPECTED_STATUS[status_code]:
                count_status[status] = count_status[status]+1
            non_matching_statuses.append({
                    'status_detail': status,
                    'status_table': status_table,
                    'url_detail': url_pep_detail,
                })

    _output_mismatches_log(non_matching_statuses)
    return _forms_result_pep(count_status)


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    results = [('Ссылка на статью', 'Заголовок', 'Редактор, Автор'), ]
    response = get_response(session, whats_new_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')

    main_div = find_tag(
        soup, 'section', attrs={'id': 'what-s-new-in-python'}
    )

    div_with_ul = find_tag(
        main_div, 'div', attrs={'class': 'toctree-wrapper'}
    )

    sections_by_python = div_with_ul.find_all('li',
                                              attrs={'class': 'toctree-l1'})

    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)
        response = get_response(session, version_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, features='lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append(
            (version_link, h1.text, dl_text)
        )
    return results


def latest_versions(session):
    session = requests_cache.CachedSession()
    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    response = get_response(session, MAIN_DOC_URL)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')

    sidebar = find_tag(soup, 'div', {'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
    else:
        raise Exception('Не найден список c версиями Python')

    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in a_tags:
        link = a_tag['href']
        text_match = re.search(pattern, a_tag.text)
        if text_match is not None:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ''
        results.append(
            (link, version, status)
        )
    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    response = get_response(session, downloads_url)
    if response is None:
        return
    soup = BeautifulSoup(response.text, features='lxml')

    main_tag = find_tag(soup, 'div', {'role': 'main'})
    table_tag = find_tag(main_tag, 'table', {'class': 'docutils'})

    pdf_a4_tag = find_tag(table_tag,
                          'a', {'href': re.compile(r'.+pdf-a4\.zip$')})
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url)
    if response is None:
        return
    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')
    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()
    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)
    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
