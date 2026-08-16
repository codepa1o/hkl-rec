import { Navigate, Route, Routes } from "react-router-dom";
import LeftSidebar from "./components/LeftSidebar";
import RightRail from "./components/RightRail";
import TopNav from "./components/TopNav";
import ProtectedRoute from "./components/ProtectedRoute";
import { AuthProvider } from "./context/AuthContext";
import { PersonaProvider } from "./context/PersonaContext";
import { ThemeProvider } from "./context/ThemeContext";
import FeedPage from "./pages/FeedPage";
import ArticleDetailPage from "./pages/ArticleDetailPage";
import SearchPage from "./pages/SearchPage";
import AuthPage from "./pages/AuthPage";

function ProductShell() {
  return (
    <ProtectedRoute>
      <PersonaProvider>
        <TopNav />
        <div className="zr-shell">
          <LeftSidebar />
          <Routes>
            <Route path="/" element={<FeedPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/articles/:newsId" element={<ArticleDetailPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <RightRail />
        </div>
      </PersonaProvider>
    </ProtectedRoute>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Routes>
          <Route path="/auth" element={<AuthPage />} />
          <Route path="/*" element={<ProductShell />} />
        </Routes>
      </AuthProvider>
    </ThemeProvider>
  );
}
