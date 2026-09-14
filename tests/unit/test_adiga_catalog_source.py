from app.services.adiga_catalog_source import (
    parse_general_universities,
    parse_programs,
    parse_tracks,
    parse_university_admission_guide,
)


def test_parses_general_university_list_with_campus() -> None:
    html = '''
        <input type="checkbox" name="searchUnvCode" id="UNI_0000019" value="0000019"/>
        <label for="UNI_0000019">서울대학교[본교] <strong>1건</strong></label>
    '''

    rows = parse_general_universities(html)
    assert [(item.official_code, item.name, item.campus_name) for item in rows] == [
        ("0000019", "서울대학교", "본교")
    ]


def test_parses_program_and_tracks_only_for_selected_codes() -> None:
    programs_html = '''
        <div class="norList vw">
          <li class="col01 left opnfldClass" unvCd="0000019" comScsbjtCd="0030001">
            <span class="body1 reg left">서울대학교[본교]</span>
          </li>
          <li class="col02 opnfldClass"><span class="body1 reg">반도체공학과</span></li>
          <li class="col03 opnfldClass"><span class="body1 reg">서울</span></li>
        </div> <!-- // 목록 영역-->
    '''
    selected_call = (
        "fnDetailPage(&quot;0000019&quot;,&quot;0030001&quot;,&quot;001&quot;,&quot;20&quot;"
        ',&quot;code&quot;,&quot;serial&quot;,&quot;B&quot;,&quot;01&quot;,&quot;01&quot;);'
    )
    other_call = 'fnDetailPage(&quot;other&quot;,&quot;other&quot;,&quot;002&quot;,&quot;20&quot;);'
    tracks_html = f'''
        <a href="#" onclick="{selected_call}">학생부위주(종합) &gt; 일반전형 </a>
        <a href="#" onclick="{other_call}">다른 대학 </a>
    '''

    programs = parse_programs(programs_html)
    tracks = parse_tracks(tracks_html, university_code="0000019", program_code="0030001")

    assert [(item.program_code, item.name, item.region) for item in programs] == [
        ("0030001", "반도체공학과", "서울")
    ]
    assert [(item.name, item.admission_type, item.recruitment_period) for item in tracks] == [
        ("학생부위주(종합) > 일반전형", "학생부위주(종합)", "수시")
    ]


def test_parses_university_guide_sections_without_flattening_tables() -> None:
    html = """
        <p class="required">2026학년도 대입특징 자료입니다.</p>
        <div><html><body>
          <p>수시에서 확인할 변화입니다.</p>
          <table><tbody>
            <tr><td>구분</td><td>2026학년도</td></tr>
            <tr><td>모집인원</td><td>100</td></tr>
          </tbody></table>
        </body></html></div>
        <p>2026학년도 대입특징 자료입니다.</p>
        <div><html><body><p>정시 안내입니다.</p></body></html></div>
        <p>2026학년도 입시가이드 자료입니다.</p>
        <div><html><body><p>전형요소를 확인하세요.</p></body></html></div>
    """

    sections = parse_university_admission_guide(html)

    assert [section["title"] for section in sections] == [
        "수시 대입특징",
        "정시 대입특징",
        "입시가이드",
    ]
    assert sections[0]["paragraphs"] == ["수시에서 확인할 변화입니다."]
    assert sections[0]["tables"] == [
        {"rows": [["구분", "2026학년도"], ["모집인원", "100"]]}
    ]
