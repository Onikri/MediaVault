import './styles.css';
import './title-page.css';
import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.jsx';
import {installI18n} from './i18n/index.js';

// The Ukrainian dictionary loads before the first render, so a Ukrainian
// device never flashes Russian interface text.
installI18n().finally(()=>createRoot(document.getElementById('root')).render(<App/>));


import './import-layout.css';
import './discovery-polish.css';
import './site-layout.css';
import './site-mobile.css';
