import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import LeftSidebar from "./components/LeftSidebar";
import RightRail from "./components/RightRail";
import TopNav from "./components/TopNav";
import ProtectedRoute from "./components/ProtectedRoute";
import { AuthProvider } from "./context/AuthContext";
import { PersonaProvider } from "./context/PersonaContext";
import { SourceSpaceProvider } from "./context/SourceSpaceContext";
import { ThemeProvider } from "./context/ThemeContext";
import FeedPage from "./pages/FeedPage";
import ArticleDetailPage from "./pages/ArticleDetailPage";
import ProfilePage from "./pages/ProfilePage";
import SearchPage from "./pages/SearchPage";
import AuthPage from "./pages/AuthPage";
import "./styles/liveNews.css";

function ProductShell() {
  const location = useLocation();
  const isProfilePage = location.pathname === "/profile";

  return (
    <ProtectedRoute>
      <div className="zr-product-app">
        <SourceSpaceProvider>
          <PersonaProvider>
            <TopNav />
            <div className={`zr-shell${isProfilePage ? " zr-shell--profile" : ""}`}>
              <LeftSidebar />
              <Routes>
                <Route path="/" element={<FeedPage />} />
                <Route path="/search" element={<SearchPage />} />
                <Route path="/profile" element={<ProfilePage />} />
                <Route
                  path="/articles/:sourceSpace/:articleId"
                  element={<ArticleDetailPage />}
                />
                <Route path="/articles/:newsId" element={<ArticleDetailPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
              {!isProfilePage && <RightRail />}
            </div>
          </PersonaProvider>
        </SourceSpaceProvider>
      </div>
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
