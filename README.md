# מערכת ניתוח הגרלות צ'אנס — הקמה חד-פעמית

## מה יש כאן
- `docs/index.html` — הדשבורד עצמו (זה מה ש-GitHub Pages יגיש)
- `docs/data/*.json` — הנתונים החיים (draws / snapshots / performance) — מתעדכנים אוטומטית
- `.github/workflows/update.yml` — התזמון שמריץ את העדכון
- `scripts/update_draws.py` — הקוד שמושך תוצאות חדשות ובודק ביצועים

## הקמה — כ-10 דקות, חד-פעמי

### 1. יצירת Repository
היכנסו ל-github.com (הרשמה חינמית אם אין חשבון) → לחצו **New repository** → תנו שם (למשל `chance-system`) → ודאו שהוא מסומן **Public** → **Create repository**.

### 2. העלאת הקבצים
בעמוד ה-Repository החדש → **Add file → Upload files** → גררו את כל התיקייה הזו (כולל התיקיות `.github`, `docs`, `scripts` עם המבנה הפנימי שלהן) → **Commit changes**.

### 3. הפעלת GitHub Pages
**Settings** (בתפריט העליון של ה-Repository) → **Pages** (בתפריט הצד) → תחת **Source** בחרו **Deploy from a branch** → **Branch: main**, **Folder: /docs** → **Save**.
תוך דקה-שתיים תקבלו קישור בסגנון `https://<שם-המשתמש-שלכם>.github.io/chance-system/` — זה הקישור הקבוע למערכת שלכם.

### 4. הפעלת Actions
**Settings → Actions → General** → ודאו ש-Actions מופעל (ברירת המחדל כן). זהו — התזמון כבר יתחיל לרוץ לבד לפי הלוח שב-`update.yml`.

### 5. בדיקה ידנית ראשונה (מומלץ)
**Actions** (בתפריט העליון) → **Update Chance draws** → **Run workflow** → **Run workflow** (כפתור ירוק) — זה מפעיל אותו מיד, לא מחכה לתזמון. אחרי כמה דקות תראו אם זה הצליח (✓ ירוק) או נכשל (✗ אדום — לחצו להיכנס ולראות את השגיאה, ותשלחו לי).

## מה לצפות בהפעלה הראשונה

כפי שכתבתי בקוד: **סביר שה-Selectors של הדף יצטרכו כיול** בפעם הראשונה. אם ה-Run נכשל או מחזיר "0 rows extracted" — זה בדיוק המקום לשלוח לי את השגיאה המדויקת מה-Log, ואני מתקן.

## שימוש שוטף

אחרי ההקמה — שום דבר. פותחים את הקישור מ-Pages בכל פעם, והוא כבר מעודכן.
