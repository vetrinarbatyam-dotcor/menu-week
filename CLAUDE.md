# Menu-Week — אפליקציית תפריט שבועי משפחתי

## הקשר
- **בעלים**: גיל קרן · vetrinarbatyam@gmail.com
- **מטרה**: תכנון תפריט שבועי לבית + רשימת קניות אוטומטית
- **שלב נוכחי**: אפיון (ראה `PLANNING.md`)
- **קהל יעד**: אישי קודם → multi-tenant בעתיד

## פרופיל המשפחה
- 2 מבוגרים (גיל + יפצוק) + 4 ילדים (11, 15, 17, 19)
- צהריים בבית: 11, 15, 17
- טבח ראשי: גיל · 30 דק' לערב מקס
- אין מגבלות (לא כשר, לא אלרגיות)
- העדפה: חלבון גבוה + דל פחמ' + גמיש לבריא
- סגנונות: ישראלי · איטלקי · אסיאתי · מזיא"ת · מקסיקני · בריא. **לא אמריקאי**

## Stack
- Frontend: React + Vite + TypeScript + Tailwind + shadcn/ui (RTL)
- Backend: FastAPI (Python 3.11)
- DB: PostgreSQL 15 + pgvector
- AI: Claude → Gemini fallback
- Bot: python-telegram-bot (אופציונלי)
- Deploy: Docker Compose על Contabo, port 3015

## ארכיטקטורה
- **Multi-tenant ready** — כל טבלה עם `family_id` UUID, אבל רק משפחה אחת בפועל
- **3 ארוחות/יום** — בוקר, צהריים (ילדים בבית), ערב
- **שישי חגיגי** + **שבת = שאריות + לפעמים בישול**
- **אירוח 2/חודש** — slot מסומן עם מנות מוכפלות

## עקרונות קוד
- כל הטקסט ב-UI **בעברית RTL**
- TypeScript strict
- API responses תמיד `{ ok, data, error }`
- Migrations עם Alembic
- Tests עם pytest + Vitest

## פיצ'רים MVP (גרסה 1.0)
1. תכנון שבוע אוטומטי בלחיצה אחת (AI)
2. מאגר 200 מתכונים seed
3. רשימת קניות אוטומטית מקובצת לפי מחלקה
4. גרירה ושחרור מתכונים בין ימים
5. "החלף מתכון" — AI מציע 3 חלופות
6. PWA — להתקין במסך הבית
7. עברית RTL מלא

## פיצ'רים עתידיים (אחרי MVP)
- בוט Telegram
- תצוגה לילדים + בקשות שינוי
- Shufersal Online integration
- Pantry (מזווה)
- AI לומד טעמים
- multi-tenant + תשלום

## פורטים על Contabo
| פרויקט | פורט |
|---|---|
| clinic-pal-hub | 80 |
| clinic-agents | 3000 |
| missed-caller | 3005 |
| invoices-plus | 3010 |
| menu-week | **3015** |

## פקודות נפוצות
```bash
# Local dev
cd ~/menu-week
docker compose up -d
docker compose logs -f api

# Deploy
git push && ssh claude-user@167.86.69.208 \
  "cd ~/menu-week && git pull && docker compose up -d --build"
```

## קישורים
- PLANNING.md — תכנון מלא
- Production: https://menu.vetbatyam.co.il (TBD)
- Repo: github.com/vetrinarbatyam-dotcor/menu-week (TBD)

## קבצי המפתח
- `backend/app/main.py` — FastAPI entry
- `backend/app/models.py` — SQLAlchemy schema
- `backend/app/services/menu_planner.py` — AI logic
- `frontend/src/pages/WeekView.tsx` — תצוגה ראשית
- `seed/recipes_200.json` — מאגר התחלתי
