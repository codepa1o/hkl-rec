import { Route, Routes } from "react-router-dom";
import LeftSidebar from "./components/LeftSidebar";
import RightRail from "./components/RightRail";
import TopNav from "./components/TopNav";
import { PersonaProvider } from "./context/PersonaContext";
import { ThemeProvider } from "./context/ThemeContext";
import FeedPage from "./pages/FeedPage";
import ArticleDetailPage from "./pages/ArticleDetailPage";
import SearchPage from "./pages/SearchPage";

export default function App() {
  return (
    <ThemeProvider>
      <PersonaProvider>
        <TopNav />
        <div className="zr-shell">
          <LeftSidebar />
          <Routes>
            <Route path="/" element={<FeedPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/articles/:articleId" element={<ArticleDetailPage />} />
          </Routes>
          <RightRail />
        </div>
      </PersonaProvider>
    </ThemeProvider>
  );
}
