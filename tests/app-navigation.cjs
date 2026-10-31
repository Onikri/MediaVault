// The supplied navbar collapses into an explicit, keyboard-operable menu.
module.exports=async function navigateApp(page,label){
 const desktop=page.getByRole('navigation',{name:'Основная навигация'});
 if(await desktop.isVisible())return desktop.getByRole('button',{name:label,exact:true}).click();
 const menu=page.getByRole('button',{name:'Открыть меню',exact:true});
 if(await menu.isVisible())await menu.click();
 await page.getByRole('navigation',{name:'Мобильная навигация'}).getByRole('button',{name:label,exact:true}).click();
};
