// Nombres en español de los géneros del dataset. Los datos quedan en inglés (son la clave
// que usan el backend y el recommender): esto es solo lo que se muestra.

const LABELS: Record<string, string> = {
  Action: "Acción",
  Adventure: "Aventura",
  Animation: "Animación",
  Biography: "Biografía",
  Comedy: "Comedia",
  Crime: "Policial",
  Documentary: "Documental",
  Drama: "Drama",
  Family: "Familia",
  Fantasy: "Fantasía",
  "Film-Noir": "Cine negro",
  History: "Historia",
  Horror: "Terror",
  Music: "Música",
  Musical: "Musical",
  Mystery: "Misterio",
  News: "Noticias",
  Romance: "Romance",
  "Sci-Fi": "Ciencia ficción",
  Short: "Cortometraje",
  Sport: "Deporte",
  "Talk-Show": "Talk show",
  Thriller: "Suspenso",
  War: "Bélica",
  Western: "Western",
};

/** Un género desconocido se muestra tal cual: mejor en inglés que vacío. */
export function genreLabel(genre: string): string {
  return LABELS[genre] ?? genre;
}
