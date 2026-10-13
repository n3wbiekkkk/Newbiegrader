/* Runtime config for split deployment.
 * Same-origin (local / all-in-one docker): leave as "".
 * Frontend on Vercel + backend elsewhere: set your backend URL, e.g.
 *   window.GRADER_API_BASE = "https://brutal-grader-api.onrender.com";
 * and set GRADER_CORS_ORIGINS on the backend to your Vercel URL.
 */
window.GRADER_API_BASE = "";
