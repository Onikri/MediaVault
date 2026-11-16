import './styles.css';
import './title-page.css';
import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.jsx';
import CrashBoundary,{reloadForNewRelease} from './CrashBoundary.jsx';
import './touch-comfort.css';
import './lazy-stage.css';
import ShortcutHost from './ShortcutSheet.jsx';
import {installI18n} from './i18n/index.js';

// The Ukrainian dictionary loads before the first render, so a Ukrainian
// device never flashes Russian interface text.
// A tab opened before a release asks for the old files of a lazily loaded
// part (a reader, a player); they are gone, so the page reloads once.
addEventListener('vite:preloadError',event=>{if(reloadForNewRelease())event.preventDefault();});
installI18n().finally(()=>createRoot(document.getElementById('root')).render(<CrashBoundary label="Сайт" className="crash-page"><App/><ShortcutHost/></CrashBoundary>));


import './import-layout.css';
import './discovery-polish.css';
import './site-layout.css';
import './site-mobile.css';
