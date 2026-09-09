export type SchoolRecordCategory = "상장" | "활동" | "봉사" | "독서" | "시험";

// The parser buffers the PDF in memory, so keep this below the Worker memory ceiling.
export const SCHOOL_RECORD_MAX_FILE_SIZE = 50 * 1024 * 1024;
export const SCHOOL_RECORD_MAX_FILE_SIZE_LABEL = "50MB";

export type SchoolRecordCourse = {
  id: string;
  grade: number;
  semester: number;
  subject: string;
  rank?: number | null;
};

export type SchoolRecordDraft = {
  id: string;
  selected: boolean;
  grade: number;
  semester: number;
  category: SchoolRecordCategory;
  subject: string;
  title: string;
  summary: string;
  completedAt: string;
  confidence: number;
  dateBasis: "document" | "inferred";
};

export type SchoolRecordParseResult = {
  fileName: string;
  totalPages: number;
  extractedCharacters: number;
  courses: SchoolRecordCourse[];
  entries: SchoolRecordDraft[];
  warnings: string[];
};

export type SchoolRecordPeriod = {
  grade: number;
  semester: number;
};

type SeteukReadingActivity = {
  author?: unknown;
  grade?: unknown;
  semester?: unknown;
  subject?: unknown;
  title?: unknown;
};

type SeteukAcademicPerformance = {
  achievement?: unknown;
  category?: unknown;
  grade?: unknown;
  rank?: unknown;
  semester?: unknown;
  subject?: unknown;
  units?: unknown;
};

type SeteukAward = {
  date?: unknown;
  grade?: unknown;
  name?: unknown;
  rank?: unknown;
  semester?: unknown;
};

type SeteukVolunteerRecord = {
  content?: unknown;
  date?: unknown;
  grade?: unknown;
  hours?: unknown;
  place?: unknown;
  semester?: unknown;
};

type SeteukActivity = {
  activity_category?: unknown;
  activity_name?: unknown;
  description?: unknown;
  grade?: unknown;
  keywords?: unknown;
  semester?: unknown;
  subject?: unknown;
};

export type SeteukAnalysisResult = {
  academic_performance?: SeteukAcademicPerformance[];
  activities?: SeteukActivity[];
  attendance?: unknown[];
  awards?: SeteukAward[];
  errors?: unknown[];
  reading_activities?: SeteukReadingActivity[];
  student_name?: unknown;
  time_logs?: unknown[];
  volunteer_records?: SeteukVolunteerRecord[];
};

const SUBJECTS = [
  "통합과학", "과학탐구실험", "물리학Ⅱ", "물리학Ⅰ", "물리학", "화학Ⅱ", "화학Ⅰ", "화학",
  "생명과학Ⅱ", "생명과학Ⅰ", "생명과학", "지구과학Ⅱ", "지구과학Ⅰ", "지구과학",
  "공통수학", "기본수학", "수학과제 탐구", "미적분", "확률과 통계", "기하", "수학Ⅰ", "수학Ⅱ", "수학",
  "공통국어", "화법과 작문", "독서와 작문", "문학", "독서", "국어",
  "공통영어", "영어 독해와 작문", "영어Ⅰ", "영어Ⅱ", "영어",
  "통합사회", "한국사", "사회문화", "생활과 윤리", "정치와 법", "경제", "사회",
  "정보", "기술·가정", "기술가정", "진로와 직업", "융합과학 탐구", "사회문제 탐구",
];

const SECTION_TITLES = /인적사항|학적사항|출결상황|수상경력|자격증|진로희망|창의적 체험활동|교과학습발달상황|세부능력 및 특기사항|독서활동상황|행동특성 및 종합의견/;

function cleanLine(value: string) {
  return value.replace(/\u0000/g, "").replace(/[\t ]+/g, " ").trim();
}

function detectSubject(line: string) {
  return SUBJECTS.find((subject) => line.includes(subject)) ?? "교과 외 활동";
}

function detectCategory(line: string, section: string): SchoolRecordCategory | null {
  if (/수상|상장|우수상|표창/.test(line) || section === "수상") return "상장";
  if (/봉사/.test(line)) return "봉사";
  if (/독서|도서|읽고|책을/.test(line) || section === "독서") return "독서";
  if (/중간고사|기말고사|정기고사|시험/.test(line)) return "시험";
  if (/대회|경진|발표회|공모전|수행평가|프로젝트|실험평가|보고서|탐구|세부능력|특기사항|발표|조사/.test(line) || section === "세특") return "활동";
  return null;
}

function extractDocumentDate(line: string, fallbackYear: number) {
  const match = line.match(/(?:(20\d{2})\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})(?:\s*일)?/);
  if (!match) return null;
  const year = Number(match[1] ?? fallbackYear);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function parseApiDate(value: unknown) {
  const source = textValue(value);
  if (!source) return null;
  const match = source.match(/(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})(?:\s*일)?/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function periodFromDate(date: string, academicStartYear: number): SchoolRecordPeriod {
  const [yearText, monthText] = date.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const schoolYearStart = month <= 2 ? year - 1 : year;
  const grade = Math.min(3, Math.max(1, schoolYearStart - academicStartYear + 1));
  const semester = month >= 3 && month <= 8 ? 1 : 2;
  return { grade, semester };
}

function inferredDate(baseYear: number, grade: number, semester: number, category: SchoolRecordCategory) {
  const year = baseYear + grade - 1;
  const monthDays: Record<SchoolRecordCategory, [string, string]> = {
    상장: ["07-12", "12-12"],
    활동: ["06-18", "11-25"],
    봉사: ["05-10", "10-15"],
    독서: ["04-18", "09-24"],
    시험: ["07-05", "12-06"],
  };
  return `${year}-${monthDays[category][semester === 1 ? 0 : 1]}`;
}

function entryTitle(line: string, category: SchoolRecordCategory, subject: string) {
  const withoutDate = line.replace(/(?:(?:20\d{2})\s*[.\-/년]\s*)?\d{1,2}\s*[.\-/월]\s*\d{1,2}(?:\s*일)?/g, "");
  const withoutSubject = withoutDate.replace(subject, "").replace(/^\s*[:：·\-]\s*/, "").trim();
  const compact = withoutSubject.replace(/\s+/g, " ");
  if (compact.length >= 4 && !SECTION_TITLES.test(compact)) return compact.slice(0, 56);
  const defaults: Record<SchoolRecordCategory, string> = {
    상장: "수상 기록",
    활동: `${subject} 활동 기록`,
    봉사: "봉사활동 기록",
    독서: `${subject} 독서 활동`,
    시험: `${subject} 시험 기록`,
  };
  return defaults[category];
}

function keyFor(grade: number, semester: number, subject: string, title: string) {
  return `${grade}-${semester}-${subject}-${title.replace(/\s/g, "").slice(0, 30)}`;
}

function textValue(value: unknown, fallback = "") {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}

function gradeValue(value: unknown) {
  const grade = Number(value);
  return Number.isInteger(grade) && grade >= 1 && grade <= 3 ? grade : 1;
}

function semesterValue(value: unknown) {
  const semester = Number(value);
  return semester === 1 || semester === 2 ? semester : 2;
}

function apiActivityCategory(item: SeteukActivity): SchoolRecordCategory {
  const source = [
    textValue(item.activity_category),
    textValue(item.activity_name),
    textValue(item.description),
    Array.isArray(item.keywords) ? item.keywords.filter((value): value is string => typeof value === "string").join(" ") : "",
  ].join(" ");
  if (/수상|상장|우수상|표창/.test(source)) return "상장";
  if (/봉사/.test(source)) return "봉사";
  if (/독서|도서|책을|읽고/.test(source)) return "독서";
  if (/시험|중간고사|기말고사/.test(source)) return "시험";
  return "활동";
}

function isSeteukAnalysisResult(value: unknown): value is SeteukAnalysisResult {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as SeteukAnalysisResult;
  return ["academic_performance", "activities", "awards", "reading_activities", "volunteer_records"].some((key) =>
    Array.isArray(candidate[key as keyof SeteukAnalysisResult]),
  );
}

export function parseSchoolRecordText(
  rawText: string,
  options: { fileName: string; totalPages: number; academicStartYear: number },
): SchoolRecordParseResult {
  const structuredText = rawText
    .replace(/(20\d{2})\s*[.]\s*(\d{1,2})\s*[.]\s*(\d{1,2})\s*[.]?/g, "\n$1-$2-$3 ")
    .replace(/([1-3]\s*학년\s*[1-2]\s*학기)/g, "\n$1\n")
    .replace(/(교과학습발달상황|세부능력 및 특기사항|독서활동상황|수상경력|창의적 체험활동상황|행동특성 및 종합의견)/g, "\n$1\n")
    .replace(/([함됨임음다])\.\s+/g, "$1.\n");
  const lines = structuredText
    .split(/\r?\n/)
    .map(cleanLine)
    .filter((line) => line.length >= 2);
  const courses = new Map<string, SchoolRecordCourse>();
  const entries = new Map<string, SchoolRecordDraft>();
  let grade = 1;
  let semester = 1;
  let section = "";

  lines.forEach((line, lineIndex) => {
    const gradeMatch = line.match(/([1-3])\s*학년/);
    const semesterMatch = line.match(/([1-2])\s*학기/);
    if (gradeMatch) grade = Number(gradeMatch[1]);
    if (semesterMatch) semester = Number(semesterMatch[1]);
    if (/^[1-3]\s*학년\s*[1-2]\s*학기$/.test(line)) {
      section = "";
      return;
    }
    if (/수상경력/.test(line)) section = "수상";
    else if (/독서활동상황/.test(line)) section = "독서";
    else if (/세부능력 및 특기사항/.test(line)) section = "세특";
    else if (/창의적 체험활동/.test(line)) section = "창체";
    else if (/교과학습발달상황/.test(line)) section = "교과";
    else if (SECTION_TITLES.test(line)) section = "";

    if (SECTION_TITLES.test(line) && line.length < 35) return;
    const foundSubjects = ["교과", "세특", "독서"].includes(section)
      ? SUBJECTS.filter((subject) => line.includes(subject))
      : [];
    foundSubjects.forEach((subject) => {
      const id = `${grade}-${semester}-${subject}`;
      courses.set(id, { id, grade, semester, subject });
    });

    const category = detectCategory(line, section);
    if (!category) return;
    const subject = detectSubject(line);
    const title = entryTitle(line, category, subject);
    const fallbackYear = options.academicStartYear + grade - 1;
    const documentDate = extractDocumentDate(line, fallbackYear);
    const id = keyFor(grade, semester, subject, title);
    if (entries.has(id)) return;
    entries.set(id, {
      id: `record-${lineIndex}-${id}`,
      selected: true,
      grade,
      semester,
      category,
      subject,
      title,
      summary: line.slice(0, 280),
      completedAt: documentDate ?? inferredDate(options.academicStartYear, grade, semester, category),
      confidence: documentDate ? 92 : subject === "교과 외 활동" ? 58 : 76,
      dateBasis: documentDate ? "document" : "inferred",
    });
  });

  const warnings: string[] = [];
  if (!courses.size) warnings.push("과목명을 충분히 찾지 못했습니다. PDF가 스캔 이미지라면 OCR이 필요할 수 있습니다.");
  if (!entries.size) warnings.push("자동 배치할 활동을 찾지 못했습니다. 텍스트형 PDF인지 확인해주세요.");
  if ([...entries.values()].some((entry) => entry.dateBasis === "inferred")) {
    warnings.push("생기부에 정확한 날짜가 없는 항목은 학기 안의 임시 날짜에 배치했습니다. 반영 전에 수정할 수 있습니다.");
  }

  return {
    fileName: options.fileName,
    totalPages: options.totalPages,
    extractedCharacters: rawText.length,
    // Keep every deduplicated course and activity. The review screen lets the
    // user deselect records before import, so truncating here would silently
    // hide valid school-record evidence.
    courses: [...courses.values()],
    entries: [...entries.values()],
    warnings,
  };
}

export function parseSchoolRecordJson(
  jsonData: unknown,
  academicStartYear: number
): SchoolRecordParseResult {
  const courses = new Map<string, SchoolRecordCourse>();
  const entries = new Map<string, SchoolRecordDraft>();
  const warnings: string[] = [];

  const result: SeteukAnalysisResult = isSeteukAnalysisResult(jsonData)
    ? jsonData
    : Array.isArray(jsonData)
      ? { reading_activities: jsonData, academic_performance: jsonData, activities: jsonData }
      : {};

  (result.reading_activities ?? []).forEach((item, index) => {
    const title = textValue(item.title);
    const author = textValue(item.author);
    if (title && author) {
      const grade = gradeValue(item.grade);
      const semester = semesterValue(item.semester);
      const subject = textValue(item.subject, "독서");

      const id = `${grade}-${semester}-${subject}`;
      const parsedRank = Number.parseInt(textValue(item.rank), 10);
      const rank = Number.isInteger(parsedRank) && parsedRank >= 1 && parsedRank <= 5 ? parsedRank : null;
      const existingCourse = courses.get(id);
      if (!existingCourse) {
        courses.set(id, { id, grade, semester, subject, rank });
      } else if (rank !== null) {
        courses.set(id, { ...existingCourse, rank });
      }

      const entryId = keyFor(grade, semester, subject, title);
      if (!entries.has(entryId)) {
        entries.set(entryId, {
          id: `json-read-${index}-${entryId}`,
          selected: true,
          grade,
          semester,
          category: "독서",
          subject,
          title: `${title} (${author})`,
          summary: `${author} 저. ${subject} 관련 독서 활동.`,
          completedAt: inferredDate(academicStartYear, grade, semester, "독서"),
          confidence: 100,
          dateBasis: "inferred",
        });
      }
    }
  });

  (result.academic_performance ?? []).forEach((item, index) => {
    const achievement = textValue(item.achievement);
    if (achievement) {
      const grade = gradeValue(item.grade);
      const semester = semesterValue(item.semester);
      const subject = textValue(item.subject, "공통");

      const id = `${grade}-${semester}-${subject}`;
      if (!courses.has(id)) {
        courses.set(id, { id, grade, semester, subject });
      }

      const title = `${subject} 학기말 성적`;
      const entryId = keyFor(grade, semester, subject, title);
      const rank = textValue(item.rank);
      const units = textValue(item.units, "-");
      const summary = `성취도: ${achievement}, 석차등급: ${rank ? `${rank}등급` : "석차없음"}, 단위: ${units}`;

      if (!entries.has(entryId)) {
        entries.set(entryId, {
          id: `json-grade-${index}-${entryId}`,
          selected: true,
          grade,
          semester,
          category: "시험",
          subject,
          title,
          summary,
          completedAt: inferredDate(academicStartYear, grade, semester, "시험"),
          confidence: 100,
          dateBasis: "inferred",
        });
      }
    }
  });

  (result.awards ?? []).forEach((item, index) => {
    const name = textValue(item.name);
    if (!name) return;

    const rank = textValue(item.rank);
    const parsedDate = parseApiDate(item.date);
    const inferredPeriod = parsedDate ? periodFromDate(parsedDate, academicStartYear) : null;
    const grade = gradeValue(item.grade ?? inferredPeriod?.grade);
    const semester = semesterValue(item.semester ?? inferredPeriod?.semester);
    const subject = "수상경력";
    const title = rank ? `${name} · ${rank}` : name;
    const entryId = keyFor(grade, semester, subject, title);
    if (entries.has(entryId)) return;

    entries.set(entryId, {
      id: `json-award-${index}-${entryId}`,
      selected: true,
      grade,
      semester,
      category: "상장",
      subject,
      title,
      summary: rank ? `${name}에서 ${rank}을 수상했습니다.` : `${name} 수상 기록입니다.`,
      completedAt: parsedDate ?? inferredDate(academicStartYear, grade, semester, "상장"),
      confidence: parsedDate ? 100 : 86,
      dateBasis: parsedDate ? "document" : "inferred",
    });
  });

  (result.volunteer_records ?? []).forEach((item, index) => {
    const content = textValue(item.content);
    const place = textValue(item.place);
    if (!content && !place) return;

    const parsedDate = parseApiDate(item.date);
    const inferredPeriod = parsedDate ? periodFromDate(parsedDate, academicStartYear) : null;
    const grade = gradeValue(item.grade ?? inferredPeriod?.grade);
    const semester = semesterValue(item.semester ?? inferredPeriod?.semester);
    const hours = textValue(item.hours);
    const title = content || "봉사활동";
    const summary = [
      place && `장소: ${place}`,
      content && `내용: ${content}`,
      hours && `시간: ${hours}시간`,
    ].filter(Boolean).join(" · ");
    const subject = "봉사활동";
    const entryId = keyFor(grade, semester, subject, `${title}-${parsedDate ?? index}`);
    if (entries.has(entryId)) return;

    entries.set(entryId, {
      id: `json-volunteer-${index}-${entryId}`,
      selected: true,
      grade,
      semester,
      category: "봉사",
      subject,
      title,
      summary: summary || "봉사활동 기록입니다.",
      completedAt: parsedDate ?? inferredDate(academicStartYear, grade, semester, "봉사"),
      confidence: parsedDate ? 100 : 86,
      dateBasis: parsedDate ? "document" : "inferred",
    });
  });

  (result.activities ?? []).forEach((item, index) => {
    const title = textValue(item.activity_name);
    const summary = textValue(item.description);
    if (!title || !summary) return;
    const grade = gradeValue(item.grade);
    const semester = semesterValue(item.semester);
    const category = apiActivityCategory(item);
    const sourceCategory = textValue(item.activity_category, "교과 외 활동");
    const subject = textValue(item.subject, sourceCategory);
    const entryId = keyFor(grade, semester, subject, title);
    if (entries.has(entryId)) return;
    entries.set(entryId, {
      id: `json-activity-${index}-${entryId}`,
      selected: true,
      grade,
      semester,
      category,
      subject,
      title,
      summary,
      completedAt: inferredDate(academicStartYear, grade, semester, category),
      confidence: 96,
      dateBasis: "inferred",
    });
  });

  courses.forEach((course, index) => {
    const title = `${course.subject} 교과 기록 확인`;
    const entryId = keyFor(course.grade, course.semester, course.subject, title);
    if (entries.has(entryId) || [...entries.values()].some((entry) =>
      entry.category === "시험" && entry.grade === course.grade && entry.semester === course.semester && entry.subject === course.subject,
    )) return;
    entries.set(entryId, {
      id: `json-course-${index}-${entryId}`,
      selected: true,
      grade: course.grade,
      semester: course.semester,
      category: "시험",
      subject: course.subject,
      title,
      summary: "성취도 세부값은 확인되지 않았지만, 학생부에서 교과 기록이 인식되었습니다. 반영 전 실제 성적 정보로 보완할 수 있습니다.",
      completedAt: inferredDate(academicStartYear, course.grade, course.semester, "시험"),
      confidence: 62,
      dateBasis: "inferred",
    });
  });

  const upstreamErrors = Array.isArray(result.errors) ? result.errors.filter(Boolean) : [];
  if (upstreamErrors.length) {
    warnings.push(`분석 과정에서 확인이 필요한 항목이 ${upstreamErrors.length}개 있습니다.`);
  }
  if (!courses.size) warnings.push("교과 성적 또는 독서 과목을 찾지 못했습니다.");
  if (!entries.size) warnings.push("분석 결과에서 반영 가능한 학생부 활동을 찾지 못했습니다.");
  if (entries.size) warnings.push("학생부 API는 활동의 정확한 날짜를 제공하지 않아 학기 안의 임시 날짜에 배치했습니다. 반영 전에 수정할 수 있습니다.");

  return {
    fileName: "structured_data.json",
    totalPages: 0,
    extractedCharacters: JSON.stringify(jsonData).length,
    courses: [...courses.values()],
    entries: [...entries.values()],
    warnings,
  };
}

export function getLatestSchoolRecordPeriod(
  parsed: Pick<SchoolRecordParseResult, "courses" | "entries">
): SchoolRecordPeriod | null {
  const periods = [
    ...parsed.courses.map((course) => ({ grade: course.grade, semester: course.semester })),
    ...parsed.entries.map((entry) => ({ grade: entry.grade, semester: entry.semester })),
  ].filter((period) =>
    [1, 2, 3].includes(period.grade) && [1, 2].includes(period.semester),
  );

  if (!periods.length) return null;

  return periods.reduce((latest, period) => {
    const latestIndex = (latest.grade - 1) * 2 + latest.semester;
    const periodIndex = (period.grade - 1) * 2 + period.semester;
    return periodIndex > latestIndex ? period : latest;
  });
}
