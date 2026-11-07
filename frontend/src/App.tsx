import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Orb from "./components/Orb";
import { Spinner, Toaster } from "./components/ui";
import { useStore } from "./lib/store";
import Chat from "./pages/Chat";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Onboarding from "./pages/Onboarding";

const Profile = lazy(() => import("./pages/Profile"));
const Memory = lazy(() => import("./pages/Memory"));
const Career = lazy(() => import("./pages/Career"));
const Projects = lazy(() => import("./pages/Projects"));
const Productivity = lazy(() => import("./pages/Productivity"));
const Import = lazy(() => import("./pages/Import"));
const Integrations = lazy(() => import("./pages/Integrations"));
const Settings = lazy(() => import("./pages/Settings"));

export default function App() {
  const { user, booting, boot } = useStore();
  useEffect(() => { boot(); }, [boot]);

  if (booting) return <div className="flex h-full items-center justify-center"><Orb size={120} /></div>;

  return (
    <BrowserRouter>
      <Toaster />
      {!user ? (
        <Routes><Route path="*" element={<Login />} /></Routes>
      ) : (
        <Routes>
          <Route path="/onboarding" element={<Onboarding />} />
          <Route path="*" element={
            <Layout>
              <Suspense fallback={<div className="flex justify-center py-20"><Spinner /></div>}>
                <Routes>
                  <Route path="/" element={user.onboarded ? <Home /> : <Navigate to="/onboarding" replace />} />
                  <Route path="/chat" element={<Chat />} />
                  <Route path="/chat/:id" element={<Chat />} />
                  <Route path="/me" element={<Profile />} />
                  <Route path="/memory" element={<Memory />} />
                  <Route path="/career" element={<Career />} />
                  <Route path="/projects" element={<Projects />} />
                  <Route path="/productivity" element={<Productivity />} />
                  <Route path="/import" element={<Import />} />
                  <Route path="/integrations" element={<Integrations />} />
                  <Route path="/settings" element={<Settings />} />
                  <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
              </Suspense>
            </Layout>
          } />
        </Routes>
      )}
    </BrowserRouter>
  );
}
