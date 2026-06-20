import { Link, Route, Routes } from "react-router-dom";
import MeetingBotPage from "./features/meetingBot/pages/MeetingBotPage.jsx";
import ThemeToggle from "./components/ThemeToggle.jsx";

// Single unified system: the advanced meeting bot (live transcript + audio/video
// recordings + optional re-transcription + source-separated MoM).
export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          🎙️ Meeting Bot
        </Link>
        <div className="topbar-spacer" />
        <ThemeToggle />
      </header>
      <main className="content">
        <Routes>
          <Route path="/" element={<MeetingBotPage />} />
          <Route path="/meetings/:id" element={<MeetingBotPage />} />
          <Route path="/meetings/:id/:module" element={<MeetingBotPage />} />
        </Routes>
      </main>
    </div>
  );
}
