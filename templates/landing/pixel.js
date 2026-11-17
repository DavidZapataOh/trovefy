// Trovefy · píxel de Meta solo en la ruta Cloudflare (resolución 23): código base con el dataset de TRACKING.md,
// únicamente PageView y ViewContent, sin autoConfig (sin eventos automáticos): los del pago los emite la tienda.
!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,
document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('set','autoConfig',false,'{{dataset_id}}');
fbq('init', '{{dataset_id}}');
fbq('track', 'PageView');
fbq('track', 'ViewContent');
