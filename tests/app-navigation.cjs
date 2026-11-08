// Desktop uses the navbar; phones use the bottom dock, and the collapsed
// menu remains a keyboard-operable fallback when the dock is not shown.
module.exports=async function navigateApp(page,label){
 const desktop=page.getByRole('navigation',{name:'Основная навигация'});
 if(await desktop.isVisible())return desktop.getByRole('button',{name:label,exact:true}).click();
 const dock=page.getByRole('navigation',{name:'Навигация',exact:true}).getByRole('button',{name:label,exact:true});
 if(await dock.isVisible())return dock.click();
 const menu=page.getByRole('button',{name:'Открыть меню',exact:true});
 if(await menu.isVisible())await menu.click();
 await page.getByRole('navigation',{name:'Мобильная навигация'}).getByRole('button',{name:label,exact:true}).click();
};
