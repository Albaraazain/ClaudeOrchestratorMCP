import React from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { LayoutDashboard, Settings, Layers, Zap } from 'lucide-react';

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const location = useLocation();

  const navItems = [
    { path: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/settings', icon: Settings, label: 'Settings' },
  ];

  return (
    <div className="flex h-screen bg-background text-text overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-64 border-r border-surfaceHighlight bg-surface/80 backdrop-blur-md flex flex-col">
        {/* Logo Area */}
        <div className="h-16 flex items-center px-6 border-b border-surfaceHighlight">
          <div className="flex items-center space-x-2 text-primary">
            <Zap className="w-6 h-6 fill-current" />
            <span className="text-lg font-bold tracking-tight text-text">Orchestrator</span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-6 px-3 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center px-3 py-2.5 rounded-lg transition-all duration-200 group ${
                  isActive || (item.path === '/' && location.path === '/')
                    ? 'bg-primary/10 text-primary shadow-sm shadow-primary/5'
                    : 'text-textMuted hover:bg-surfaceHighlight hover:text-text'
                }`
              }
            >
              <item.icon className="w-5 h-5 mr-3 transition-transform group-hover:scale-110" />
              <span className="font-medium">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        {/* User/Status Area (Bottom) */}
        <div className="p-4 border-t border-surfaceHighlight bg-surface/60">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-primary to-secondary flex items-center justify-center text-xs font-bold text-white shadow-lg shadow-primary/20">
              AI
            </div>
            <div>
              <p className="text-sm font-medium text-text">Claude Agent</p>
              <p className="text-xs text-textMuted">Online • v2.0</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto relative">
        {/* Background Gradients */}
        <div className="absolute top-0 left-0 w-full h-96 bg-gradient-to-b from-surface to-transparent -z-10 pointer-events-none" />
        
        <div className="max-w-7xl mx-auto p-8">
            {children}
        </div>
      </main>
    </div>
  );
};

export default Layout;
